import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from immunity import ImmunitySystem
from risk_limits import REDIS_CHANNEL, bootstrap_limits, get_active_limits
from circuit_breaker import CircuitBreaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
immunity = ImmunitySystem()
breaker = CircuitBreaker(max_failures=5, reset_timeout=300)

_last_reset_day = -1


def clear_operational_halt(reset_counters: bool = False) -> None:
    immunity._system_halted = False
    immunity._halt_until = 0.0
    if reset_counters:
        immunity._daily_loss = 0.0
        immunity._daily_trades = 0
        immunity._open_positions = 0
        log.info("Immunity halt cleared — daily counters reset")
    else:
        log.info("Immunity halt cleared — daily counters kept")


def expire_stale_halt() -> None:
    if immunity._system_halted and immunity._halt_until > 0 and time.time() >= immunity._halt_until:
        immunity._system_halted = False
        immunity._halt_until = 0.0


async def limits_listener(redis: aioredis.Redis):
    """Reload risk limits from Redis on publish or periodic poll."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(REDIS_CHANNEL)
    log.info("Risk limits listener active (%s)", REDIS_CHANNEL)

    async def poll():
        while True:
            await bootstrap_limits(redis)
            immunity.reevaluate_halt()
            await write_immunity_status(redis)
            await asyncio.sleep(5)

    async def on_message():
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            await bootstrap_limits(redis)
            immunity.reevaluate_halt()
            await write_immunity_status(redis)
            lim = get_active_limits()
            log.info(
                "Risk limits reloaded — leverage=%s pos=%s%% daily_loss=%s%% open=%s",
                lim.max_leverage,
                round(lim.max_position_pct * 100, 2),
                round(lim.max_daily_loss_pct * 100, 2),
                lim.max_open_positions,
            )

    await bootstrap_limits(redis)
    immunity.reevaluate_halt()
    await write_immunity_status(redis)
    await asyncio.gather(poll(), on_message())


async def halt_control_listener(redis: aioredis.Redis):
    pubsub = redis.pubsub()
    await pubsub.subscribe("ch:immunity:clear_halt", "ch:trading:restart")
    log.info("Immunity halt control listener active")
    async for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        try:
            raw = msg.get("data")
            if isinstance(raw, bytes):
                raw = raw.decode()
            payload = json.loads(raw) if raw else {}
            reset = bool(payload.get("reset_counters", True))
            clear_operational_halt(reset_counters=reset)
        except Exception as e:
            log.error(f"Halt clear listener error: {e}")


async def order_approval_loop(redis: aioredis.Redis):
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
            lim = get_active_limits()
            request = json.loads(item[1])
            portfolio_value = float(request.get("portfolio_value", 10000))
            daily_pnl = float(request.get("daily_pnl", 0))
            approved, reason = immunity.check_order(request, portfolio_value, daily_pnl)
            if approved:
                immunity._daily_trades += 1
                immunity._open_positions = min(
                    immunity._open_positions + 1, lim.max_open_positions
                )
            response = {
                "request_id": request.get("request_id"),
                "approved": approved,
                "reason": reason,
            }
            response_key = f"immunity:response:{request.get('request_id', 'unknown')}"
            await redis.set(response_key, json.dumps(response), ex=30)
            log.info(
                f"Order {'APPROVED' if approved else 'REJECTED'}: {request.get('symbol')} — {reason}"
            )
        except Exception as e:
            log.error(f"Order approval error: {e}")
            if not breaker.is_open:
                breaker.record_failure()


async def position_close_listener(redis: aioredis.Redis):
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


async def write_immunity_status(redis: aioredis.Redis) -> None:
    """Publish current limits + counters to Redis (dashboard /system reads this)."""
    expire_stale_halt()
    lim = get_active_limits()
    status = {
        "max_position_pct": round(lim.max_position_pct * 100, 2),
        "max_daily_loss_pct": round(lim.max_daily_loss_pct * 100, 2),
        "max_leverage": lim.max_leverage,
        "max_open_positions": lim.max_open_positions,
        "min_confidence_pct": round(lim.min_immunity_confidence * 100, 2),
        "min_signal_confidence_pct": round(lim.min_signal_confidence * 100, 2),
        "max_trades_per_day": lim.max_trades_per_day,
        "system_halted": immunity._system_halted,
        "circuit_open": breaker.is_open,
        "daily_trades": immunity._daily_trades,
        "open_positions": immunity._open_positions,
        "daily_loss_pct": round(immunity._daily_loss * 100, 3),
        "updated_at": time.time(),
        "limits_updated_at": lim.updated_at,
        "limits_updated_by": lim.updated_by,
    }
    await redis.set("immunity:status", json.dumps(status), ex=120)


async def status_writer_loop(redis: aioredis.Redis):
    while True:
        try:
            await write_immunity_status(redis)
            await redis.set("system:heartbeat:immunity_system", str(time.time()), ex=120)
        except Exception as e:
            log.error(f"Status writer error: {e}")
        await asyncio.sleep(5)


async def main():
    log.info("immunity_system starting — dynamic risk limits from Redis/DB")
    redis = await aioredis.from_url(REDIS_URL)
    redis_sub = await aioredis.from_url(REDIS_URL)
    redis_ctl = await aioredis.from_url(REDIS_URL)
    redis_lim = await aioredis.from_url(REDIS_URL)
    from risk_limits import bootstrap_limits

    await bootstrap_limits(redis)
    immunity.reevaluate_halt()
    await write_immunity_status(redis)
    await redis.set("system:heartbeat:immunity_system", str(time.time()), ex=120)
    await asyncio.gather(
        order_approval_loop(redis),
        status_writer_loop(redis),
        position_close_listener(redis_sub),
        halt_control_listener(redis_ctl),
        limits_listener(redis_lim),
    )


if __name__ == "__main__":
    asyncio.run(main())
