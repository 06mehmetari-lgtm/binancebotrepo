"""Single source of truth for open positions — OMS + Shadow → Redis for AI, signals, dashboard."""

from __future__ import annotations

import json
import os
import time

import redis.asyncio as aioredis

PORTFOLIO_KEY = "portfolio:state:v1"
_LAST_SNAPSHOT_TS = 0.0
SNAPSHOT_INTERVAL_SEC = 60


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
            "ladder": pos.get("ladder"),
        })

    # Tek sembol = tek kayıt (shadow A/B/C mükerrer sayılmasın)
    deduped: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for p in positions:
        key = (p["symbol"], p.get("source", "oms"), str(p.get("shadow_id", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    positions = deduped

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
    await redis.publish("ch:portfolio:update", json.dumps({"ts": state["updated_at"]}))

    global _LAST_SNAPSHOT_TS
    now = time.time()
    if now - _LAST_SNAPSHOT_TS >= SNAPSHOT_INTERVAL_SEC:
        _LAST_SNAPSHOT_TS = now
        try:
            trade_hist_raw = await redis.lrange("oms:trade_history", 0, 999)
            trades = []
            for r in trade_hist_raw:
                try:
                    trades.append(json.loads(r))
                except json.JSONDecodeError:
                    pass
            trades.sort(key=lambda t: t.get("closed_at", 0))
            equity = float(os.environ.get("PORTFOLIO_VALUE", "10000"))
            for t in trades:
                equity += float(t.get("pnl_usdt", 0))
            for p in positions:
                sym = p.get("symbol", "")
                if not sym:
                    continue
                ticker_raw = await redis.get(f"binance:ticker:{sym.lower()}")
                price = 0.0
                if ticker_raw:
                    try:
                        td = json.loads(ticker_raw)
                        d = td.get("data", td)
                        bid = float(d.get("b", 0) or 0)
                        ask = float(d.get("a", bid) or bid)
                        price = (bid + ask) / 2 if bid and ask else bid or ask
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass
                entry = float(p.get("entry_price", 0))
                size = float(p.get("size_usd", 0))
                direction = p.get("direction", "long")
                if price > 0 and entry > 0 and size > 0:
                    upnl_pct = (
                        ((price - entry) / entry) * 100
                        if direction == "long"
                        else ((entry - price) / entry) * 100
                    )
                    equity += size * (upnl_pct / 100)
            snapshot = {
                "ts": int(now),
                "equity": round(equity, 2),
                "trade_count": len(trades),
                "open_positions": len(positions),
            }
            await redis.lpush("portfolio:pnl:snapshots", json.dumps(snapshot))
            await redis.ltrim("portfolio:pnl:snapshots", 0, 719)
        except Exception:
            pass

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
