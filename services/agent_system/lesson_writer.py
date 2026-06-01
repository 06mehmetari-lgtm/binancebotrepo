"""Trade lesson writer — generates AI lessons from closed trades and stores in Redis."""
import json
import logging
import time

import redis.asyncio as aioredis

log = logging.getLogger(__name__)

REDIS_URL_DEFAULT = "redis://redis:6379"
MAX_LESSONS = 50
MAX_LESSONS_PER_SYMBOL = 10


async def _generate_lesson(trade_data: dict, redis: aioredis.Redis) -> str:
    from llm_client import chat_completion

    symbol = trade_data.get("symbol", "UNKNOWN")
    side = trade_data.get("side", "long").upper()
    entry = float(trade_data.get("entry_price", 0))
    exit_ = float(trade_data.get("exit_price", 0))
    hold_s = float(trade_data.get("hold_seconds", 0))
    confidence = float(trade_data.get("confidence", 0))
    close_reason = trade_data.get("close_reason", "unknown")

    pnl_pct = ((exit_ - entry) / entry * (1 if side == "LONG" else -1)) if entry else 0
    hold_h = hold_s / 3600
    outcome = "WIN" if pnl_pct > 0 else "LOSS"

    ctx_raw = await redis.get(f"context:latest:{symbol}")
    ctx = json.loads(ctx_raw) if ctx_raw else {}
    regime = ctx.get("regime", "unknown")

    verdict_raw = await redis.get(f"agents:verdict:{symbol}")
    verdict = json.loads(verdict_raw) if verdict_raw else {}

    prompt = (
        f"Analyze this completed crypto futures trade and generate a trading lesson.\n\n"
        f"TRADE:\n"
        f"Symbol: {symbol} | Direction: {side} | Outcome: {outcome}\n"
        f"Entry: ${entry:,.4f} | Exit: ${exit_:,.4f} | P&L: {pnl_pct:+.2%}\n"
        f"Hold time: {hold_h:.1f}h | Close reason: {close_reason}\n"
        f"Signal confidence: {confidence:.2f} | Market regime: {regime}\n"
    )

    if verdict:
        prompt += (
            f"Agent consensus: {verdict.get('consensus', 0):.0%} | "
            f"Agents voted: {verdict.get('direction', 'unknown')}\n"
        )

    prompt += (
        f"\nWrite a concise trade lesson (3-5 sentences):\n"
        f"1. Why this trade {'succeeded' if pnl_pct > 0 else 'failed'}\n"
        f"2. Which signals/conditions were decisive\n"
        f"3. One specific actionable rule for future trades\n\n"
        f"Start with '[{symbol} {side} {pnl_pct:+.1%}]' then the lesson. Be specific with numbers. English only."
    )

    try:
        content, provider = await chat_completion(prompt, max_tokens=300)
        log.info(f"LessonWriter: ders üretildi {symbol} {outcome} [{provider}]")
        return content
    except Exception as e:
        log.warning(f"LessonWriter: LLM hatası {symbol}: {e} — kural tabanlı ders")
        if pnl_pct > 0:
            return (
                f"[{symbol} {side} {pnl_pct:+.1%}] Trade succeeded with {confidence:.0%} confidence "
                f"in {regime} regime, closed after {hold_h:.1f}h ({close_reason}). "
                f"Rule: {regime} regime + confidence>={confidence:.0%} is favorable for {side} entries."
            )
        else:
            return (
                f"[{symbol} {side} {pnl_pct:+.1%}] Trade failed. Closed via {close_reason} after {hold_h:.1f}h. "
                f"Confidence was {confidence:.0%} in {regime} regime. "
                f"Rule: Avoid holding {side} positions in {regime} regime when exit triggered by {close_reason}."
            )


async def _store_lesson(redis: aioredis.Redis, lesson: str, symbol: str, trade_data: dict, pnl_pct: float):
    entry = {
        "lesson": lesson,
        "symbol": symbol,
        "side": trade_data.get("side", "unknown"),
        "pnl_pct": round(pnl_pct, 4),
        "outcome": "WIN" if pnl_pct > 0 else "LOSS",
        "close_reason": trade_data.get("close_reason", "unknown"),
        "confidence": round(float(trade_data.get("confidence", 0)), 3),
        "ts": time.time(),
    }
    entry_json = json.dumps(entry)

    pipe = redis.pipeline()
    pipe.lpush("training:lessons", entry_json)
    pipe.ltrim("training:lessons", 0, MAX_LESSONS - 1)
    pipe.lpush(f"training:lessons:{symbol}", entry_json)
    pipe.ltrim(f"training:lessons:{symbol}", 0, MAX_LESSONS_PER_SYMBOL - 1)
    await pipe.execute()
    log.info(f"LessonWriter: kaydedildi {symbol} {entry['outcome']} {pnl_pct:+.2%}")


async def process_trade_for_lesson(redis: aioredis.Redis, trade_data: dict):
    symbol = trade_data.get("symbol", "")
    if not symbol:
        return

    entry = float(trade_data.get("entry_price", 0))
    exit_ = float(trade_data.get("exit_price", 0))
    side = trade_data.get("side", "long")
    pnl_pct = ((exit_ - entry) / entry * (1 if side == "long" else -1)) if entry else 0

    lesson = await _generate_lesson(trade_data, redis)
    await _store_lesson(redis, lesson, symbol, trade_data, pnl_pct)


async def lesson_writer_loop(redis_url: str):
    """Subscribe to ch:trade_closed and generate AI lessons for each closed trade."""
    import os
    url = redis_url or os.getenv("REDIS_URL", REDIS_URL_DEFAULT)

    redis_data = await aioredis.from_url(url)
    redis_pubsub = await aioredis.from_url(url)

    log.info("LessonWriter: başlatılıyor — ch:trade_closed dinleniyor")
    pubsub = redis_pubsub.pubsub()
    await pubsub.subscribe("ch:trade_closed")

    async for message in pubsub.listen():
        if message is None or message["type"] != "message":
            continue
        try:
            trade_data = json.loads(message["data"])
            await process_trade_for_lesson(redis_data, trade_data)
        except Exception as e:
            log.error(f"LessonWriter: işlem hatası: {e}")
