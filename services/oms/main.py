import asyncio
import json
import logging
import os
import time
import uuid

import redis.asyncio as aioredis

from order_manager import OrderManager
from binance_executor import BinanceExecutor
from position_tracker import PositionTracker
from audit_logger import AuditLogger

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
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
        }
        await redis.lpush("oms:trade_history", json.dumps(trade))
        await redis.ltrim("oms:trade_history", 0, 999)
        await redis.publish("ch:trade_closed", json.dumps(trade))
        log.info(f"Position CLOSED: {symbol} {direction} pnl={pnl_pct:.2%} (${pnl_usdt:+.2f})")

    await redis.delete(f"oms:position:{symbol}")


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


async def process_signal(redis: aioredis.Redis, symbol: str):
    global _last_reset_day, _daily_pnl

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

    if not signal.get("is_valid"):
        return

    direction = signal["direction"]
    pos_raw = await redis.get(f"oms:position:{symbol}")

    # If we have a position in the opposite direction, close it first
    if pos_raw:
        pos = json.loads(pos_raw)
        if pos.get("direction") == direction:
            return  # Already positioned correctly
        # Close opposite position
        price = await get_price(redis, symbol)
        if price > 0:
            await close_position(redis, symbol, pos, price)

    if direction == "flat":
        return

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

    if DRY_RUN:
        log.info(f"[DRY_RUN] {symbol} {direction.upper()} size=${size_usd:.2f} @ {price:.4f}")
    else:
        log.info(f"[LIVE] Executing {symbol} {direction.upper()} size=${size_usd:.2f} @ {price:.4f}")

    # Track the paper/live position
    await redis.set(f"oms:position:{symbol}", json.dumps({
        "symbol": symbol, "direction": direction,
        "size_usd": size_usd, "entry_price": price,
        "entry_time": time.time(), "entry_signal": signal,
    }), ex=86400)


async def main():
    mode = "DRY_RUN" if DRY_RUN else "LIVE"
    log.info(f"OMS starting — {mode} mode — portfolio=${PORTFOLIO_VALUE:.0f}")
    redis = await aioredis.from_url(REDIS_URL)

    symbols: list[str] = []
    last_refresh = 0.0

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


if __name__ == "__main__":
    asyncio.run(main())
