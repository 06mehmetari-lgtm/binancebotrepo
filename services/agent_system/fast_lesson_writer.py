"""
Fast rule-based lesson writer — no LLM required.
Listens to ch:trade_closed and immediately writes a structured lesson to training:lessons.
"""
import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")


def _generate_lesson(trade: dict) -> dict | None:
    symbol       = trade.get("symbol", "UNKNOWN")
    direction    = trade.get("direction", "unknown")
    regime       = trade.get("regime", trade.get("entry_regime", "unknown"))
    close_reason = trade.get("close_reason", "unknown")
    pnl_pct      = float(trade.get("pnl_pct", 0))
    confidence   = float(trade.get("confidence", 0))
    ml_score     = float(trade.get("ml_score") or 0)
    rr           = float(trade.get("risk_reward") or 0)
    hold_seconds = float(trade.get("hold_seconds", 0))
    outcome      = "WIN" if pnl_pct > 0 else "LOSS"

    lesson_text = None
    category    = "trade_outcome"

    if outcome == "LOSS":
        if close_reason == "stop_loss":
            counter = (direction == "short" and regime == "trending_up") or \
                      (direction == "long"  and regime == "trending_down")
            if counter:
                lesson_text = (
                    f"{symbol} {direction.upper()} {regime} stop_loss {pnl_pct:.2%} "
                    f"→ {regime}'da {direction} açma"
                )
                category = "regime_direction_mismatch"
            elif regime == "volatile":
                lesson_text = (
                    f"{symbol} {direction.upper()} volatile stop {pnl_pct:.2%} "
                    f"→ volatil dönemde daha geniş stop kullan"
                )
                category = "volatile_stop"
            else:
                lesson_text = (
                    f"{symbol} {direction.upper()} stop_loss {pnl_pct:.2%} "
                    f"conf={confidence:.2f} regime={regime}"
                )
                category = "stop_loss_general"
        elif close_reason == "signal_flip":
            lesson_text = (
                f"{symbol} {direction.upper()} signal_flip {pnl_pct:.2%} "
                f"conf={confidence:.2f} → sinyal değişmeden önce giriş yanlıştı"
            )
            category = "signal_flip_loss"
        elif close_reason == "take_profit":
            lesson_text = (
                f"{symbol} {direction.upper()} TP hit ama zarar: "
                f"R:R={rr:.2f} conf={confidence:.2f} {pnl_pct:.2%}"
            )
            category = "commission_drain"
        else:
            lesson_text = (
                f"{symbol} {direction.upper()} {close_reason} {pnl_pct:.2%} "
                f"regime={regime} conf={confidence:.2f}"
            )
            category = "loss_general"
    else:  # WIN
        if close_reason == "take_profit":
            lesson_text = (
                f"{symbol} {direction.upper()} TP {pnl_pct:.2%} "
                f"conf={confidence:.2f} regime={regime} R:R={rr:.2f} → başarılı giriş"
            )
            category = "successful_tp"
        elif close_reason == "stop_loss":
            lesson_text = (
                f"{symbol} {direction.upper()} stop tetiklendi kar ile {pnl_pct:.2%} "
                f"→ stop çok dar ayarlı, erken çıktık"
            )
            category = "early_exit_win"
        else:
            lesson_text = (
                f"{symbol} {direction.upper()} {close_reason} {pnl_pct:.2%} "
                f"conf={confidence:.2f} regime={regime} → iyi strateji"
            )
            category = "win_general"

    if lesson_text is None:
        return None

    return {
        "symbol":       symbol,
        "direction":    direction,
        "side":         direction,
        "pnl_pct":      round(pnl_pct, 6),
        "outcome":      outcome,
        "close_reason": close_reason,
        "confidence":   confidence,
        "regime":       regime,
        "ml_score":     ml_score,
        "risk_reward":  rr,
        "hold_seconds": hold_seconds,
        "lesson":       lesson_text,
        "category":     category,
        "ts":           time.time(),
        "source":       "fast_lesson_writer",
    }


async def fast_lesson_loop(redis_url: str):
    """Subscribe to ch:trade_closed and write lessons instantly — no LLM needed."""
    redis = await aioredis.from_url(redis_url)
    pubsub = redis.pubsub()
    await pubsub.subscribe("ch:trade_closed")
    log.info("[FastLessonWriter] Subscribed to ch:trade_closed")

    async for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        try:
            trade  = json.loads(msg["data"])
            lesson = _generate_lesson(trade)
            if lesson:
                await redis.lpush("training:lessons", json.dumps(lesson))
                await redis.ltrim("training:lessons", 0, 999)
                log.info(
                    f"[FastLessonWriter] {lesson['outcome']} {lesson['symbol']} "
                    f"→ {lesson['category']} {lesson['pnl_pct']:.2%}"
                )
        except Exception as e:
            log.error(f"[FastLessonWriter] error: {e}")
