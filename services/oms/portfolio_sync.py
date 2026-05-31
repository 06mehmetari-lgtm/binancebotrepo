"""Single source of truth for open positions — OMS + Shadow → Redis for AI, signals, dashboard."""

from __future__ import annotations

import json
import time

import redis.asyncio as aioredis

PORTFOLIO_KEY = "portfolio:state:v1"


async def _scan(redis: aioredis.Redis, pattern: str) -> list[str]:
    keys: list[str] = []
    cursor = 0
    while True:
        cursor, batch = await redis.scan(cursor, match=pattern, count=200)
        keys.extend(k.decode() if isinstance(k, bytes) else k for k in batch)
        if cursor == 0:
            break
    return keys


async def publish_portfolio_state(redis: aioredis.Redis) -> dict:
    positions: list[dict] = []

    for key in await _scan(redis, "oms:position:*"):
        symbol = key.split(":")[-1]
        raw = await redis.get(key)
        if not raw:
            continue
        try:
            pos = json.loads(raw)
        except json.JSONDecodeError:
            continue
        positions.append({
            "symbol": symbol,
            "direction": pos.get("direction", "long"),
            "size_usd": float(pos.get("size_usd", 0)),
            "entry_price": float(pos.get("entry_price", 0)),
            "entry_time": pos.get("entry_time"),
            "source": "oms",
        })

    for key in await _scan(redis, "shadow:positions:*"):
        parts = key.split(":")
        if len(parts) < 4:
            continue
        shadow_id, symbol = parts[2], parts[3]
        raw = await redis.get(key)
        if not raw:
            continue
        try:
            pos = json.loads(raw)
        except json.JSONDecodeError:
            continue
        positions.append({
            "symbol": symbol,
            "direction": pos.get("direction", "long"),
            "size_usd": float(pos.get("size_usd", 0)),
            "entry_price": float(pos.get("price", 0)),
            "entry_time": pos.get("time"),
            "source": "shadow",
            "shadow_id": shadow_id,
        })

    long_n = sum(1 for p in positions if p["direction"] == "long")
    short_n = sum(1 for p in positions if p["direction"] == "short")

    state = {
        "updated_at": time.time(),
        "total_open": len(positions),
        "oms_open": sum(1 for p in positions if p["source"] == "oms"),
        "shadow_open": sum(1 for p in positions if p["source"] == "shadow"),
        "long_positions": long_n,
        "short_positions": short_n,
        "positions": positions,
    }
    await redis.set(PORTFOLIO_KEY, json.dumps(state), ex=120)
    return state


async def get_open_position(redis: aioredis.Redis, symbol: str) -> dict | None:
    """OMS position takes precedence over shadow for trade decisions."""
    raw = await redis.get(f"oms:position:{symbol}")
    if raw:
        try:
            pos = json.loads(raw)
            pos["symbol"] = symbol
            pos["source"] = "oms"
            return pos
        except json.JSONDecodeError:
            pass
    raw = await redis.get(PORTFOLIO_KEY)
    if raw:
        try:
            state = json.loads(raw)
            for p in state.get("positions", []):
                if p.get("symbol") == symbol and p.get("source") == "oms":
                    return p
        except json.JSONDecodeError:
            pass
    return None
