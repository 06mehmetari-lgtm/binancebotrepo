import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from paper_trader import PaperTrader
from shadow_evaluator import ShadowEvaluator
from promotion_engine import PromotionEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOLS_RAW = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
SYMBOLS = [s.strip() for s in SYMBOLS_RAW.split(",") if s.strip()]
PORTFOLIO_VALUE = float(os.getenv("PORTFOLIO_VALUE", "10000"))

trader = PaperTrader(initial_capital=PORTFOLIO_VALUE)
SHADOW_IDS = ["SHADOW_A", "SHADOW_B", "SHADOW_C"]


async def simulate_tick(redis: aioredis.Redis, symbol: str):
    sig_raw = await redis.get(f"signal:latest:{symbol}")
    if not sig_raw:
        return
    signal = json.loads(sig_raw)
    direction = signal.get("direction")
    if direction == "flat":
        return

    # Get current price from ticker
    ticker_raw = await redis.get(f"binance:ticker:{symbol.lower()}")
    if not ticker_raw:
        return
    ticker = json.loads(ticker_raw)
    ticker_data = ticker.get("data", ticker)
    price = float(ticker_data.get("b", ticker_data.get("best_bid", 0)))
    if price <= 0:
        return

    confidence = float(signal.get("confidence", 0.5))
    size_usd = PORTFOLIO_VALUE * 0.05 * confidence

    for shadow_id in SHADOW_IDS:
        # Close opposite positions first
        pos_key = f"shadow:positions:{shadow_id}:{symbol}"
        pos_raw = await redis.get(pos_key)
        if pos_raw:
            pos = json.loads(pos_raw)
            if pos.get("direction") != direction:
                result = trader.execute(shadow_id, symbol, "SELL", price, 0)
                if result:
                    await redis.delete(pos_key)
                    await redis.lpush(f"shadow:trades:{shadow_id}", json.dumps(result))
                    await redis.ltrim(f"shadow:trades:{shadow_id}", 0, 999)
                    await redis.publish("ch:trade_closed", json.dumps({
                        "shadow_id": shadow_id, "symbol": symbol, **result
                    }))

        # Open new position if none exists
        if not await redis.exists(pos_key):
            side = "BUY" if direction == "long" else "SELL"
            result = trader.execute(shadow_id, symbol, "BUY", price, size_usd)
            if result:
                await redis.set(pos_key, json.dumps({
                    "direction": direction, "price": price,
                    "size_usd": size_usd, "time": time.time()
                }), ex=86400)


async def report_loop(redis: aioredis.Redis):
    while True:
        leaderboard = trader.leaderboard()
        await redis.set("shadow:leaderboard", json.dumps(leaderboard), ex=300)
        for entry in leaderboard:
            if entry["promotion_ready"]:
                log.info(f"PROMOTION READY: {entry['shadow_id']} Sharpe={entry['sharpe']:.2f} WR={entry['win_rate']:.1%}")
        summary = ", ".join(f"{e['shadow_id']} S={e['sharpe']:.2f}" for e in leaderboard)
        log.info(f"Shadow leaderboard: [{summary}]")
        await asyncio.sleep(300)


async def main():
    log.info("shadow_system starting")
    redis = await aioredis.from_url(REDIS_URL)
    await asyncio.gather(
        _trading_loop(redis),
        report_loop(redis),
    )


async def _trading_loop(redis: aioredis.Redis):
    while True:
        for symbol in SYMBOLS:
            try:
                await simulate_tick(redis, symbol)
            except Exception as e:
                log.error(f"Shadow tick error {symbol}: {e}")
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
