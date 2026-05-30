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
SYMBOLS_RAW = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
SYMBOLS = [s.strip() for s in SYMBOLS_RAW.split(",") if s.strip()]
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
PORTFOLIO_VALUE = float(os.getenv("PORTFOLIO_VALUE", "10000"))


async def request_immunity_approval(redis: aioredis.Redis, order_dict: dict) -> bool:
    """Send order to immunity system queue and wait for response."""
    request_id = str(uuid.uuid4())[:8]
    order_dict["request_id"] = request_id
    order_dict["portfolio_value"] = PORTFOLIO_VALUE

    daily_pnl_raw = await redis.get("oms:daily_pnl")
    order_dict["daily_pnl"] = float(daily_pnl_raw or 0)

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
    log.warning("Immunity system did not respond in time — rejecting order")
    return False


async def process_signal(redis: aioredis.Redis, symbol: str):
    sig_raw = await redis.get(f"signal:latest:{symbol}")
    if not sig_raw:
        return
    signal = json.loads(sig_raw)

    if signal.get("direction") == "flat":
        return

    # Check if we already have a position
    pos_raw = await redis.get(f"oms:position:{symbol}")
    has_position = bool(pos_raw)

    direction = signal["direction"]
    confidence = float(signal["confidence"])
    kelly = float(signal["kelly_fraction"])

    size_usd = PORTFOLIO_VALUE * kelly * confidence

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

    # Skip if we'd be opening in the same direction we already hold
    if has_position:
        pos = json.loads(pos_raw)
        if pos.get("direction") == direction:
            return

    approved = await request_immunity_approval(redis, order_request)
    if not approved:
        return

    if DRY_RUN:
        log.info(f"[DRY_RUN] Would execute: {symbol} {direction} size=${size_usd:.2f}")
        # Still track as paper position
        await redis.set(f"oms:position:{symbol}", json.dumps({
            "symbol": symbol, "direction": direction,
            "size_usd": size_usd, "entry_time": time.time(),
            "entry_signal": signal
        }), ex=86400)
    else:
        log.info(f"Executing live order: {symbol} {direction} size=${size_usd:.2f}")
        # Live execution would happen here via BinanceExecutor


async def main():
    mode = "DRY_RUN" if DRY_RUN else "LIVE"
    log.info(f"OMS starting — {mode} mode — portfolio=${PORTFOLIO_VALUE:.0f}")
    redis = await aioredis.from_url(REDIS_URL)

    while True:
        for symbol in SYMBOLS:
            try:
                await process_signal(redis, symbol)
            except Exception as e:
                log.error(f"OMS error for {symbol}: {e}")
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
