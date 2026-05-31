"""Emergency trading halt flags (flatten logic lives in oms/main.py)."""

from __future__ import annotations

import json
import time

import redis.asyncio as aioredis

HALT_KEY = "system:trading:halted"
EMERGENCY_CHANNEL = "ch:emergency:close_all"
LAST_EMERGENCY_KEY = "system:emergency:last"


async def set_trading_halt(redis: aioredis.Redis, reason: str, by: str = "dashboard") -> None:
    await redis.set(
        HALT_KEY,
        json.dumps({"halted": True, "reason": reason, "by": by, "since": time.time()}),
        ex=86400 * 7,
    )


async def clear_trading_halt(redis: aioredis.Redis) -> None:
    await redis.delete(HALT_KEY)


async def is_trading_halted(redis: aioredis.Redis) -> tuple[bool, str]:
    raw = await redis.get(HALT_KEY)
    if not raw:
        return False, ""
    try:
        data = json.loads(raw)
        if data.get("halted"):
            return True, data.get("reason", "trading halted")
    except json.JSONDecodeError:
        return True, "trading halted"
    return False, ""


async def trigger_emergency_close(redis: aioredis.Redis, by: str = "dashboard") -> None:
    await set_trading_halt(redis, "ACIL DURUM — tüm pozisyonlar kapatılıyor", by=by)
    payload = json.dumps({"ts": time.time(), "by": by, "action": "close_all"})
    await redis.publish(EMERGENCY_CHANNEL, payload)
    await redis.set(LAST_EMERGENCY_KEY, payload, ex=86400)
