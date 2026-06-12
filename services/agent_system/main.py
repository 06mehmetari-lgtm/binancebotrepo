import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from debate_agent import DebateAgent
from position_guard import position_guard_loop
from explanation_builder import (
    build_consensus_reasoning,
    build_dissent_risk,
    build_probability_breakdown,
    build_trade_targets,
    format_vote_reasoning,
)
from rag_context import fetch_trade_lessons

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOL_REFRESH_INTERVAL = 300
AGENT_BATCH_SIZE = int(os.getenv("AGENT_BATCH_SIZE", "120"))
AGENT_CYCLE_SEC = float(os.getenv("AGENT_CYCLE_SEC", "3"))

debate = DebateAgent()


async def discover_symbols(redis: aioredis.Redis) -> list[str]:
    keys = await redis.keys("features:latest:*")
    if not keys:
        return []
    return sorted(
        (k.decode() if isinstance(k, bytes) else k).replace("features:latest:", "").upper()
        for k in keys
    )


async def run_debate_for_symbol(redis: aioredis.Redis, symbol: str):
    feat_raw = await redis.get(f"features:latest:{symbol}")
    ctx_raw = await redis.get(f"context:latest:{symbol}")

    if not feat_raw or not ctx_raw:
        return

    features = json.loads(feat_raw)
    context = json.loads(ctx_raw)

    pos_raw = await redis.get(f"oms:position:{symbol}")
    open_position = None
    if pos_raw:
        try:
            open_position = json.loads(pos_raw)
            open_position["symbol"] = symbol
            context["open_position"] = open_position
        except json.JSONDecodeError:
            pass

    lessons = await fetch_trade_lessons(redis, symbol)
    result = await debate.run_debate(symbol, features, context, lessons=lessons)

    votes_payload = [
        {
            "agent": f"{v.agent_name}_agent",
            "signal": v.signal,
            "confidence": v.confidence,
            "direction": v.signal,
            "reasoning": format_vote_reasoning(
                v.agent_name, v.signal, v.confidence, v.reasoning
            ),
        }
        for v in result.all_votes
    ]

    await redis.set(f"agents:verdicts:{symbol}", json.dumps(votes_payload), ex=180)

    ticker_raw = await redis.get(f"binance:ticker:{symbol.lower()}")
    price = float(features.get("close") or features.get("last_price") or 0)
    if not price and ticker_raw:
        try:
            td = json.loads(ticker_raw)
            d = td.get("data", td)
            bid = float(d.get("b", 0) or 0)
            ask = float(d.get("a", bid) or bid)
            price = (bid + ask) / 2 if bid else 0
        except Exception:
            pass
    atr = float(features.get("atr") or features.get("atr_14") or 0)
    if not atr and price:
        atr = price * 0.01

    consensus_reasoning = build_consensus_reasoning(
        symbol,
        result.final_signal,
        result.final_confidence,
        result.majority_reasoning,
        features,
        context,
        lessons=lessons or None,
    )
    dissent_risk = build_dissent_risk(result.all_votes, result.final_signal)
    probabilities = build_probability_breakdown(
        result.all_votes,
        result.final_signal,
        result.final_confidence,
        result.consensus_strength,
    )
    targets = build_trade_targets(
        result.final_signal,
        price,
        atr,
        result.final_confidence,
        min(result.final_confidence * 0.05, 0.05),
    )

    trade_action = "none"
    direction = result.final_signal
    if open_position:
        pos_dir = open_position.get("direction", "long")
        if result.final_signal == "flat":
            trade_action = "close"
            consensus_reasoning = (
                f"Açık {pos_dir.upper()} pozisyon aktif. AI çıkış öneriyor (FLAT). "
                + consensus_reasoning
            )
        elif result.final_signal == pos_dir:
            trade_action = "hold"
            direction = pos_dir
            consensus_reasoning = (
                f"Açık {pos_dir.upper()} pozisyon — tutma: {consensus_reasoning}"
            )
        elif result.final_signal in ("long", "short") and result.final_signal != pos_dir:
            trade_action = "reverse"

    buy_votes = sum(1 for v in result.all_votes if getattr(v, "signal", None) == "long")
    sell_votes = sum(1 for v in result.all_votes if getattr(v, "signal", None) == "short")

    verdict = {
        "symbol": symbol,
        "direction": direction,
        "buy_votes": buy_votes,
        "sell_votes": sell_votes,
        "confidence": result.final_confidence,
        "consensus": result.consensus_strength,
        "reasoning": result.majority_reasoning,
        "consensus_reasoning": consensus_reasoning,
        "dissent_risk": dissent_risk,
        "probabilities": probabilities,
        "targets": targets,
        "trade_lessons": lessons,
        "vote_count": len(result.all_votes),
        "timestamp": time.time(),
        "trade_action": trade_action,
        "open_position": open_position,
    }
    await redis.set(f"agents:verdict:{symbol}", json.dumps(verdict), ex=180)
    await redis.publish(f"ch:agents:{symbol}", symbol)

    if result.final_signal != "flat":
        log.info(
            f"[{symbol}] {result.final_signal.upper()} conf={result.final_confidence:.2f} "
            f"consensus={result.consensus_strength:.0%} ({len(result.all_votes)} agents)"
        )


async def weight_update_loop(redis: aioredis.Redis):
    """Periodically load updated weights from Redis."""
    while True:
        weights_raw = await redis.get("agents:weights")
        if weights_raw:
            weights = json.loads(weights_raw)
            debate.weights.update(weights)
        await asyncio.sleep(300)


_learn_debate_at: dict[str, float] = {}
LEARN_DEBATE_COOLDOWN = float(os.getenv("LEARN_DEBATE_COOLDOWN_SEC", "45"))


async def _handle_learn_message(redis_cmd: aioredis.Redis, msg: dict) -> None:
    sym = msg.get("data")
    if isinstance(sym, bytes):
        sym = sym.decode()
    symbol = str(sym).upper()
    if not symbol.endswith("USDT"):
        ch = msg.get("channel", b"")
        if isinstance(ch, bytes):
            ch = ch.decode()
        symbol = ch.split(":")[-1].upper()
    now = time.time()
    if now - _learn_debate_at.get(symbol, 0) < LEARN_DEBATE_COOLDOWN:
        return
    _learn_debate_at[symbol] = now
    await run_debate_for_symbol(redis_cmd, symbol)


async def _handle_trade_closed(redis_cmd: aioredis.Redis, msg: dict) -> None:
    trade = json.loads(msg["data"])
    symbol = trade.get("symbol")
    if not symbol:
        return
    pnl = float(trade.get("pnl_pct", 0))
    pos_dir = trade.get("direction") or trade.get("side", "long")
    if pos_dir in ("BUY", "SELL_SHORT"):
        return
    was_win = pnl > 0

    votes_raw = await redis_cmd.get(f"agents:verdicts:{symbol}")
    if not votes_raw:
        return
    votes = json.loads(votes_raw)
    weights = dict(debate.weights)
    for v in votes:
        agent_key = (v.get("agent") or "").replace("_agent", "")
        if not agent_key:
            continue
        voted = v.get("signal", "flat")
        if voted == "flat":
            continue
        correct = (voted == pos_dir) == was_win
        debate.update_weights(agent_key, correct)
        weights[agent_key] = debate.weights.get(agent_key, 1.0)
    await redis_cmd.set("agents:weights", json.dumps(weights), ex=86400 * 7)


async def _reload_runtime_llm_keys(redis_cmd: aioredis.Redis) -> None:
    try:
        from llm_runtime_keys import REDIS_KEY, load_overrides_from_redis

        raw = await redis_cmd.get(REDIS_KEY)
        load_overrides_from_redis(raw)
    except Exception as e:
        log.warning(f"runtime llm keys reload: {e}")


async def _publish_llm_health(redis_cmd: aioredis.Redis) -> None:
    try:
        from llm_health import REDIS_KEY, build_health_payload

        payload = await asyncio.get_event_loop().run_in_executor(None, build_health_payload)
        await redis_cmd.set(REDIS_KEY, json.dumps(payload), ex=600)
    except Exception:
        log.warning("llm health publish failed", exc_info=True)


async def llm_keys_refresh_loop(redis_cmd: aioredis.Redis):
    await _reload_runtime_llm_keys(redis_cmd)
    while True:
        await asyncio.sleep(30)
        await _reload_runtime_llm_keys(redis_cmd)


async def llm_health_loop(redis_cmd: aioredis.Redis):
    await _publish_llm_health(redis_cmd)
    interval = float(os.getenv("LLM_HEALTH_PROBE_SEC", "120"))
    while True:
        await asyncio.sleep(interval)
        await _publish_llm_health(redis_cmd)


async def pubsub_listener(redis_cmd: aioredis.Redis):
    """
    Dedicated Redis connection for pub/sub only.
    Never mix pubsub.listen() with GET/SET on the same connection (redis-py requirement).
    """
    redis_sub = await aioredis.from_url(REDIS_URL)
    pubsub = redis_sub.pubsub()
    await pubsub.subscribe("ch:trade_closed", "ch:llm:keys_updated")
    await pubsub.psubscribe("ch:learn:*")
    log.info("agent_system: pubsub listener (trade_closed + learn + llm keys)")
    try:
        async for msg in pubsub.listen():
            try:
                mtype = msg.get("type")
                if mtype == "message":
                    ch = msg.get("channel", b"")
                    if isinstance(ch, bytes):
                        ch = ch.decode()
                    if ch == "ch:llm:keys_updated":
                        await _reload_runtime_llm_keys(redis_cmd)
                        await _publish_llm_health(redis_cmd)
                        await _publish_llm_status(redis_cmd)
                        continue
                    await _handle_trade_closed(redis_cmd, msg)
                elif mtype == "pmessage":
                    await _handle_learn_message(redis_cmd, msg)
            except Exception as e:
                log.error(f"pubsub handler: {e}")
    finally:
        try:
            await pubsub.aclose()
        except Exception:
            pass
        try:
            await redis_sub.aclose()
        except Exception:
            pass


_debate_semaphore: asyncio.Semaphore | None = None


def _debate_sem() -> asyncio.Semaphore:
    global _debate_semaphore
    if _debate_semaphore is None:
        n = int(os.getenv("AGENT_CONCURRENCY", "20"))
        _debate_semaphore = asyncio.Semaphore(max(1, n))
    return _debate_semaphore


async def debate_loop(redis: aioredis.Redis):
    active_set: set[str] = set()
    last_refresh = 0.0
    cycle_offset = 0

    async def _debate_one(symbol: str):
        async with _debate_sem():
            try:
                await run_debate_for_symbol(redis, symbol)
            except Exception as e:
                log.exception(f"Debate error for {symbol}: {e}")

    while True:
        now = time.time()
        if now - last_refresh > SYMBOL_REFRESH_INTERVAL or not active_set:
            syms = await discover_symbols(redis)
            if syms:
                active_set = set(syms)
                log.info(
                    f"agent_system: {len(active_set)} symbols — "
                    f"batches of {AGENT_BATCH_SIZE}"
                )
            last_refresh = now

        symbols_list = sorted(active_set)
        n = len(symbols_list)
        if n == 0:
            await asyncio.sleep(AGENT_CYCLE_SEC)
            continue

        priority: list[str] = []
        pf_raw = await redis.get("portfolio:state:v1")
        if pf_raw:
            try:
                pf = json.loads(pf_raw)
                priority = list(
                    dict.fromkeys(
                        p["symbol"]
                        for p in pf.get("positions", [])
                        if p.get("source") == "oms" and p.get("symbol")
                    )
                )
            except json.JSONDecodeError:
                pass

        batch_n = min(AGENT_BATCH_SIZE, n)
        batch: list[str] = []
        used: set[str] = set()
        for sym in priority:
            if sym in active_set and len(batch) < batch_n:
                batch.append(sym)
                used.add(sym)
        idx = 0
        while len(batch) < batch_n and idx < n:
            sym = symbols_list[(cycle_offset + idx) % n]
            if sym not in used:
                batch.append(sym)
                used.add(sym)
            idx += 1
        cycle_offset = (cycle_offset + batch_n) % n

        await asyncio.gather(*[_debate_one(s) for s in batch])
        await redis.set("system:heartbeat:agent_system", str(time.time()), ex=120)
        await _publish_llm_status(redis)
        await asyncio.sleep(AGENT_CYCLE_SEC)


async def _supervise(name: str, coro_fn):
    """Run coroutine factory in a loop; isolate failures."""
    while True:
        try:
            await coro_fn()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(f"{name} crashed — retry in 5s")
            await asyncio.sleep(5)


async def _publish_llm_status(redis) -> None:
    try:
        import json
        from llm_providers import collect_keys
        from llm_status import build_llm_status_payload

        payload = build_llm_status_payload()
        await redis.set(
            "system:llm:status",
            json.dumps(payload),
            ex=300,
        )
        n = len(collect_keys("GROQ_API_KEY"))
        if n:
            log.debug("llm status redis ok — groq_keys=%s", n)
    except Exception:
        log.warning("llm status publish failed", exc_info=True)


async def main():
    log.info("agent_system starting — 9-agent debate team — dynamic symbols")
    redis = await aioredis.from_url(REDIS_URL)
    await _reload_runtime_llm_keys(redis)
    await _publish_llm_status(redis)
    await _publish_llm_health(redis)
    try:
        async def limits_refresh_loop():
            from risk_limits import bootstrap_limits
            await bootstrap_limits(redis)
            while True:
                await bootstrap_limits(redis)
                await asyncio.sleep(5)

        await asyncio.gather(
            _supervise("debate_loop", lambda: debate_loop(redis)),
            _supervise(
                "position_guard",
                lambda: position_guard_loop(redis, run_debate_for_symbol),
            ),
            _supervise("weight_update", lambda: weight_update_loop(redis)),
            _supervise("pubsub", lambda: pubsub_listener(redis)),
            _supervise("risk_limits", limits_refresh_loop),
            _supervise("llm_keys", lambda: llm_keys_refresh_loop(redis)),
            _supervise("llm_health", lambda: llm_health_loop(redis)),
        )
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
