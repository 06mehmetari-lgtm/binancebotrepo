import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis

from order_manager import OrderManager
from binance_executor import BinanceExecutor
from position_tracker import PositionTracker
from audit_logger import AuditLogger
from promotion_gate import check_live_trading_allowed, DRY_RUN
from trade_store import schedule_save
from emergency import EMERGENCY_CHANNEL, is_trading_halted
from portfolio_sync import publish_portfolio_state
from guard_listener import guard_listener

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
PORTFOLIO_VALUE = float(os.getenv("PORTFOLIO_VALUE", "10000"))
SYMBOL_REFRESH_INTERVAL = 300

# Running daily P&L (reset at UTC midnight)
_daily_pnl = 0.0
_last_reset_day = -1


async def discover_symbols(redis: aioredis.Redis) -> list[str]:
    """Discover tradeable symbols from live signal keys."""
    keys = await redis.keys("signal:latest:*")
    if keys:
        return sorted(
            (k.decode() if isinstance(k, bytes) else k).split(":")[-1]
            for k in keys
        )
    # Fallback to env var
    raw = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
    return [s.strip() for s in raw.split(",") if s.strip()]


async def request_immunity_approval(redis: aioredis.Redis, order_dict: dict) -> bool:
    """Send order to immunity system queue and wait for response."""
    request_id = str(uuid.uuid4())[:8]
    order_dict["request_id"] = request_id
    order_dict["portfolio_value"] = PORTFOLIO_VALUE
    order_dict["daily_pnl"] = _daily_pnl

    await redis.rpush("immunity:requests", json.dumps(order_dict))
    response_key = f"immunity:response:{request_id}"

    for _ in range(30):  # wait up to 3 seconds
        resp_raw = await redis.get(response_key)
        if resp_raw:
            resp = json.loads(resp_raw)
            await redis.delete(response_key)
            if not resp["approved"]:
                log.info(f"Order rejected by immunity: {resp['reason']}")
            return resp["approved"]
        await asyncio.sleep(0.1)
    log.warning("Immunity system did not respond — rejecting order")
    return False


async def close_position(redis: aioredis.Redis, symbol: str, pos: dict, current_price: float):
    """Close an existing position and record P&L."""
    global _daily_pnl
    entry_price = pos.get("entry_price", current_price)
    direction = pos.get("direction", "long")
    size_usd = pos.get("size_usd", 0)

    if entry_price > 0 and size_usd > 0:
        if direction == "long":
            pnl_pct = (current_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_price) / entry_price
        pnl_pct -= 0.001  # 0.10% round-trip fee
        pnl_usdt = size_usd * pnl_pct
        _daily_pnl += pnl_usdt
        await redis.set("oms:daily_pnl", str(round(_daily_pnl, 4)))
        trade = {
            "symbol": symbol, "direction": direction,
            "entry_price": entry_price, "exit_price": current_price,
            "pnl_pct": round(pnl_pct, 6), "pnl_usdt": round(pnl_usdt, 4),
            "size_usd": size_usd, "source": "oms",
            "closed_at": time.time(),
            "hold_seconds": time.time() - pos.get("entry_time", time.time()),
            "entry_signal": pos.get("entry_signal"),
        }
        await redis.lpush("oms:trade_history", json.dumps(trade))
        await redis.ltrim("oms:trade_history", 0, 999)
        await redis.publish("ch:trade_closed", json.dumps(trade))
        schedule_save(trade)
        log.info(f"Position CLOSED: {symbol} {direction} pnl={pnl_pct:.2%} (${pnl_usdt:+.2f})")

    await redis.delete(f"oms:position:{symbol}")
    await publish_portfolio_state(redis)


async def get_price(redis: aioredis.Redis, symbol: str) -> float:
    """Get current mid price for a symbol."""
    ticker_raw = await redis.get(f"binance:ticker:{symbol.lower()}")
    if not ticker_raw:
        return 0.0
    ticker = json.loads(ticker_raw)
    ticker_data = ticker.get("data", ticker)
    bid = float(ticker_data.get("b", 0))
    ask = float(ticker_data.get("a", bid))
    return (bid + ask) / 2 if bid > 0 and ask > 0 else bid or ask


async def flatten_all_positions(redis: aioredis.Redis) -> int:
    """Emergency: close every open OMS position at market."""
    closed = 0
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="oms:position:*", count=100)
        for key in keys:
            k = key.decode() if isinstance(key, bytes) else key
            symbol = k.split(":")[-1]
            pos_raw = await redis.get(k)
            if not pos_raw:
                continue
            try:
                pos = json.loads(pos_raw)
            except json.JSONDecodeError:
                continue
            price = await get_price(redis, symbol)
            if price > 0:
                await close_position(redis, symbol, pos, price)
                closed += 1
        if cursor == 0:
            break
    return closed


async def emergency_listener(redis: aioredis.Redis):
    pubsub = redis.pubsub()
    await pubsub.subscribe(EMERGENCY_CHANNEL)
    log.info("OMS subscribed to emergency close channel")
    async for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        try:
            n = await flatten_all_positions(redis)
            log.warning(f"EMERGENCY: flattened {n} OMS position(s)")
            await redis.lpush(
                "activity:feed",
                json.dumps({
                    "type": "emergency",
                    "msg": f"Acil durum: {n} OMS pozisyonu kapatıldı",
                    "time": time.time(),
                }),
            )
        except Exception as e:
            log.error(f"Emergency flatten error: {e}")


async def process_signal(redis: aioredis.Redis, symbol: str):
    global _last_reset_day, _daily_pnl

    halted, _reason = await is_trading_halted(redis)
    if halted:
        return

    # Daily reset
    day = int(time.time() // 86400)
    if day != _last_reset_day:
        _daily_pnl = 0.0
        _last_reset_day = day
        await redis.set("oms:daily_pnl", "0")

    sig_raw = await redis.get(f"signal:latest:{symbol}")
    if not sig_raw:
        return
    signal = json.loads(sig_raw)

    direction = signal.get("direction", "flat")
    trade_action = signal.get("trade_action", "")
    pos_raw = await redis.get(f"oms:position:{symbol}")

    # Flat / close signal → exit open position (fixes AI flat vs open position desync)
    if direction == "flat" or trade_action == "close":
        if pos_raw:
            pos = json.loads(pos_raw)
            price = await get_price(redis, symbol)
            if price > 0:
                log.info(f"[{symbol}] Closing position — signal={direction} action={trade_action}")
                await close_position(redis, symbol, pos, price)
        return

    if not signal.get("is_valid"):
        return

    # If we have a position in the opposite direction, close it first
    if pos_raw:
        pos = json.loads(pos_raw)
        if pos.get("direction") == direction:
            return  # Already positioned correctly
        price = await get_price(redis, symbol)
        if price > 0:
            await close_position(redis, symbol, pos, price)

    confidence = float(signal.get("confidence", 0))
    kelly = float(signal.get("kelly_fraction", 0.01))
    size_usd = min(PORTFOLIO_VALUE * kelly * confidence, PORTFOLIO_VALUE * 0.05)

    if size_usd < 10:
        return

    price = await get_price(redis, symbol)
    if price <= 0:
        return

    order_request = {
        "symbol": symbol,
        "side": "BUY" if direction == "long" else "SELL",
        "size_usd": size_usd,
        "leverage": 1.0,
        "confidence": confidence,
        "signal_source": signal.get("source", "signal_engine"),
        "crisis_level": signal.get("crisis_level", 0),
        "drift_status": signal.get("drift_status", "STABLE"),
    }

    approved = await request_immunity_approval(redis, order_request)
    if not approved:
        return

    live_ok, live_reason = await check_live_trading_allowed(redis)
    if not live_ok:
        log.warning(f"Order blocked (live gate): {symbol} — {live_reason}")
        await redis.set(
            "system:live_trading:blocked",
            json.dumps({"symbol": symbol, "reason": live_reason, "ts": time.time()}),
            ex=120,
        )
        return

    if DRY_RUN:
        log.info(f"[DRY_RUN] {symbol} {direction.upper()} size=${size_usd:.2f} @ {price:.4f}")
    else:
        log.info(f"[LIVE] Executing {symbol} {direction.upper()} size=${size_usd:.2f} @ {price:.4f}")
        # BinanceExecutor wired when API keys + promotion gate both pass

    # Track the paper/live position
    await redis.set(f"oms:position:{symbol}", json.dumps({
        "symbol": symbol, "direction": direction,
        "size_usd": size_usd, "entry_price": price,
        "entry_time": time.time(), "entry_signal": signal,
    }), ex=86400)
    await publish_portfolio_state(redis)


async def snapshot_portfolio(redis: aioredis.Redis):
    """Write hourly equity snapshot for portfolio equity curve."""
    while True:
        try:
            trade_hist_raw = await redis.lrange("oms:trade_history", 0, 999)
            trades = []
            for r in trade_hist_raw:
                try:
                    trades.append(json.loads(r))
                except Exception:
                    pass
            trades.sort(key=lambda t: t.get("closed_at", 0))
            equity = PORTFOLIO_VALUE
            for t in trades:
                equity += t.get("pnl_usdt", 0)
            snapshot = {
                "ts": int(time.time()),
                "equity": round(equity, 2),
                "trade_count": len(trades),
            }
            await redis.lpush("portfolio:pnl:snapshots", json.dumps(snapshot))
            await redis.ltrim("portfolio:pnl:snapshots", 0, 719)  # 30 days × 24h
        except Exception as e:
            log.warning(f"Snapshot error: {e}")
        await asyncio.sleep(3600)  # hourly


async def main():
    mode = "DRY_RUN" if DRY_RUN else "LIVE"
    log.info(f"OMS starting — {mode} mode — portfolio=${PORTFOLIO_VALUE:.0f}")
    redis = await aioredis.from_url(REDIS_URL)

    symbols: list[str] = []
    last_refresh = 0.0

    async def portfolio_sync_loop():
        while True:
            try:
                await publish_portfolio_state(redis)
            except Exception as e:
                log.debug(f"portfolio sync: {e}")
            await asyncio.sleep(5)

    async def signal_loop():
        nonlocal symbols, last_refresh
        while True:
            now = time.time()
            if now - last_refresh > SYMBOL_REFRESH_INTERVAL or not symbols:
                symbols = await discover_symbols(redis)
                last_refresh = now
                log.info(f"OMS tracking {len(symbols)} symbols")

            for symbol in symbols:
                try:
                    await process_signal(redis, symbol)
                except Exception as e:
                    log.error(f"OMS error for {symbol}: {e}")
            await asyncio.sleep(5)

    async def apply_guard_close(redis_client: aioredis.Redis, symbol: str, pos: dict, dec: dict):
        price = await get_price(redis_client, symbol)
        if price > 0:
            await close_position(redis_client, symbol, pos, price)
            await redis_client.lpush(
                "activity:feed",
                json.dumps({
                    "type": "guard_close",
                    "symbol": symbol,
                    "action": dec.get("action"),
                    "reason": dec.get("reason", "")[:200],
                    "upnl_pct": dec.get("unrealized_pct"),
                    "time": time.time(),
                }),
            )
            await redis_client.ltrim("activity:feed", 0, 499)

    redis_em = await aioredis.from_url(REDIS_URL)
    redis_guard = await aioredis.from_url(REDIS_URL)
    await asyncio.gather(
        signal_loop(),
        portfolio_sync_loop(),
        snapshot_portfolio(redis),
        emergency_listener(redis_em),
        guard_listener(redis_guard, apply_guard_close),
    )


if __name__ == "__main__":
    asyncio.run(main())
