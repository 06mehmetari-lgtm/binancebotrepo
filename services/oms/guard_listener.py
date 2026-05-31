"""OMS — AI position guard çıkış sinyallerini uygular."""

from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from emergency import is_trading_halted

log = logging.getLogger(__name__)
GUARD_CHANNEL = "ch:position:guard"


async def guard_listener(redis: aioredis.Redis, close_fn) -> None:
    """close_fn(redis, symbol, pos, decision_dict) must flatten the OMS position."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(GUARD_CHANNEL)
    log.info("OMS subscribed to AI position guard channel")
    async for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        try:
            dec = json.loads(msg["data"])
            if dec.get("source") != "oms":
                continue
            action = dec.get("action", "hold")
            if action not in ("close", "emergency_close"):
                continue
            symbol = dec.get("symbol")
            if not symbol:
                continue
            halted, _ = await is_trading_halted(redis)
            if halted and action != "emergency_close":
                continue
            pos_raw = await redis.get(f"oms:position:{symbol}")
            if not pos_raw:
                continue
            pos = json.loads(pos_raw)
            log.warning(
                f"[GUARD→OMS] Closing {symbol}: {dec.get('reason', '')[:120]}"
            )
            await close_fn(redis, symbol, pos, dec)
        except Exception as e:
            log.error(f"guard_listener: {e}")
