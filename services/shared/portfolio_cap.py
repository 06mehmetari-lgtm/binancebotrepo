"""Kullanıcı portföy bakiyesi (USD) — dashboard input → Redis → OMS/Shadow boyutlandırma."""

from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

CAPITAL_KEY = "portfolio:capital:v1"
TRY_KEY = "portfolio:try:v1"
PUB_CHANNEL = "ch:portfolio:updated"


def _parse_cap_raw(raw: str | bytes | None) -> float:
    if not raw:
        return 0.0
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return 0.0
    if not isinstance(data, dict):
        return 0.0
    for key in ("usd_cap", "portfolio_usd", "cap_usd", "usd_capital"):
        v = float(data.get(key, 0) or 0)
        if v > 0:
            return v
    return 0.0


def default_cap_usd() -> float:
    explicit = os.getenv("PORTFOLIO_VALUE", "").strip()
    if explicit:
        try:
            return float(explicit)
        except ValueError:
            pass
    try:
        from portfolio_try import portfolio_value_usd

        return float(portfolio_value_usd())
    except Exception:
        return 10_000.0


def cap_from_redis_raw(capital_raw: str | None, try_raw: str | None) -> float:
    v = _parse_cap_raw(capital_raw)
    if v > 0:
        return v
    v = _parse_cap_raw(try_raw)
    if v > 0:
        return v
    return default_cap_usd()


async def load_cap_usd(redis) -> float:
    try:
        capital_raw = await redis.get(CAPITAL_KEY)
        try_raw = await redis.get(TRY_KEY)
        c = capital_raw.decode() if isinstance(capital_raw, bytes) else capital_raw
        t = try_raw.decode() if isinstance(try_raw, bytes) else try_raw
        return cap_from_redis_raw(c, t)
    except Exception as e:
        logger.warning("load_cap_usd failed: %s", e)
        return default_cap_usd()


def load_cap_usd_sync(redis_sync) -> float:
    try:
        c = redis_sync.get(CAPITAL_KEY)
        t = redis_sync.get(TRY_KEY)
        if isinstance(c, bytes):
            c = c.decode()
        if isinstance(t, bytes):
            t = t.decode()
        return cap_from_redis_raw(c, t)
    except Exception:
        return default_cap_usd()


async def save_cap_usd(
    redis,
    usd_cap: float,
    *,
    source: str = "dashboard",
    updated_by: str = "dashboard",
) -> dict:
    usd_cap = round(float(usd_cap), 2)
    if usd_cap < 100:
        raise ValueError("usd_cap minimum 100")
    if usd_cap > 50_000_000:
        raise ValueError("usd_cap maximum 50000000")
    payload = {
        "usd_cap": usd_cap,
        "source": source,
        "updated_at": time.time(),
        "updated_by": updated_by,
        "fee_per_side_pct": float(os.getenv("TRADE_FEE_PCT_PER_SIDE", "0.001")),
    }
    body = json.dumps(payload)
    await redis.set(CAPITAL_KEY, body)
    # Mirror — shadow/oms eski key okuyabilsin
    await redis.set(
        TRY_KEY,
        json.dumps({
            "usd_cap": usd_cap,
            "portfolio_usd": usd_cap,
            "source": source,
            "updated_at": payload["updated_at"],
            "updated_by": updated_by,
        }),
        ex=86400 * 7,
    )
    await redis.publish(PUB_CHANNEL, body)
    return payload


def sizing_preview(
    usd_cap: float,
    *,
    max_open: int = 30,
    max_position_pct: float = 0.05,
    confidence: float = 0.65,
    leverage: float = 3.0,
) -> dict:
    slot = usd_cap / max(max_open, 1)
    max_pos = usd_cap * max_position_pct
    margin = min(max_pos, slot * 0.92) * min(confidence, 0.85)
    notional = margin * max(1.0, leverage)
    return {
        "usd_cap": usd_cap,
        "slot_budget_usd": round(slot, 2),
        "max_margin_per_trade_usd": round(max_pos, 2),
        "example_margin_usd": round(margin, 2),
        "example_notional_usd": round(notional, 2),
        "max_open_positions": max_open,
    }
