import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from immunity import (
    ImmunitySystem,
    MAX_POSITION_PCT, MAX_DAILY_LOSS_PCT, MAX_LEVERAGE,
    MAX_OPEN_POSITIONS, MIN_CONFIDENCE, MAX_TRADES_PER_DAY,
)
from circuit_breaker import CircuitBreaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
immunity = ImmunitySystem()
breaker = CircuitBreaker(max_failures=5, reset_timeout=300)

_last_reset_day = -1


async def order_approval_loop(redis: aioredis.Redis):
    """Listen for order requests on Redis list immunity:requests, respond with approval."""
    global _last_reset_day
    log.info("ImmunitySystem listening for order requests")
    while True:
        day = int(time.time() // 86400)
        if day != _last_reset_day:
            immunity.reset_daily()
            _last_reset_day = day
            log.info("Daily immunity limits reset")

        item = await redis.blpop("immunity:requests", timeout=1)
        if not item:
            continue
        try:
            request = json.loads(item[1])
            portfolio_value = float(request.get("portfolio_value", 10000))
            daily_pnl = float(request.get("daily_pnl", 0))
            approved, reason = immunity.check_order(request, portfolio_value, daily_pnl)
            if approved:
                immunity._daily_trades += 1
                immunity._open_positions = min(immunity._open_positions + 1, MAX_OPEN_POSITIONS)
            response = {"request_id": request.get("request_id"), "approved": approved, "reason": reason}
            response_key = f"immunity:response:{request.get('request_id', 'unknown')}"
            await redis.set(response_key, json.dumps(response), ex=30)
            log.info(f"Order {'APPROVED' if approved else 'REJECTED'}: {request.get('symbol')} — {reason}")
        except Exception as e:
            log.error(f"Order approval error: {e}")
            if not breaker.is_open:
                breaker.record_failure()


async def position_close_listener(redis: aioredis.Redis):
    """Listen for closed trades to update open position count and daily pnl."""
    pubsub = redis.pubsub()
    await pubsub.subscribe("ch:trade_closed")
    async for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        try:
            trade = json.loads(msg["data"])
            pnl_pct = float(trade.get("pnl_pct", 0))
            immunity.record_trade_result(pnl_pct, float(os.getenv("PORTFOLIO_VALUE", "10000")))
            immunity._open_positions = max(0, immunity._open_positions - 1)
        except Exception as e:
            log.error(f"Position close listener error: {e}")


async def status_writer_loop(redis: aioredis.Redis):
    """Write immunity status to Redis every 30s for dashboard monitoring."""
    while True:
        try:
            status = {
                "max_position_pct": MAX_POSITION_PCT * 100,
                "max_daily_loss_pct": MAX_DAILY_LOSS_PCT * 100,
                "max_leverage": MAX_LEVERAGE,
                "max_open_positions": MAX_OPEN_POSITIONS,
                "min_confidence_pct": MIN_CONFIDENCE * 100,
                "max_trades_per_day": MAX_TRADES_PER_DAY,
                "system_halted": immunity._system_halted,
                "circuit_open": breaker.is_open,
                "daily_trades": immunity._daily_trades,
                "open_positions": immunity._open_positions,
                "daily_loss_pct": round(immunity._daily_loss * 100, 3),
                "updated_at": time.time(),
            }
            await redis.set("immunity:status", json.dumps(status), ex=120)
        except Exception as e:
            log.error(f"Status writer error: {e}")
        await asyncio.sleep(30)


async def main():
    log.info("immunity_system starting — ABSOLUTE LIMITS ACTIVE")
    redis = await aioredis.from_url(REDIS_URL)
    # Create separate connection for pubsub
    redis_sub = await aioredis.from_url(REDIS_URL)
    await asyncio.gather(
        order_approval_loop(redis),
        status_writer_loop(redis),
        position_close_listener(redis_sub),
    )


if __name__ == "__main__":
    asyncio.run(main())
