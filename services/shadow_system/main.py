import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from paper_trader import PaperTrader
from shadow_evaluator import ShadowEvaluator
from promotion_engine import PromotionEngine
from trade_store import schedule_save

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
PORTFOLIO_VALUE = float(os.getenv("PORTFOLIO_VALUE", "10000"))
SYMBOL_REFRESH_INTERVAL = 300


async def discover_symbols(redis: aioredis.Redis) -> list[str]:
    keys = await redis.keys("features:latest:*")
    symbols = [
        (k.decode() if isinstance(k, bytes) else k).split(":")[-1]
        for k in keys
    ]
    return sorted(symbols) if symbols else ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


trader = PaperTrader(initial_capital=PORTFOLIO_VALUE)
SHADOW_IDS = ["SHADOW_A", "SHADOW_B", "SHADOW_C"]


async def simulate_tick(redis: aioredis.Redis, symbol: str):
    sig_raw = await redis.get(f"signal:latest:{symbol}")
    if not sig_raw:
        return
    signal = json.loads(sig_raw)
    direction = signal.get("direction")
    if direction == "flat" or not signal.get("is_valid"):
        return

    # Get current price
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
        pos_key = f"shadow:positions:{shadow_id}:{symbol}"
        pos_raw = await redis.get(pos_key)

        if pos_raw:
            pos = json.loads(pos_raw)
            if pos.get("direction") != direction:
                # Close opposite position with correct side
                pos_direction = pos.get("direction", "long")
                close_side = "SELL" if pos_direction == "long" else "BUY_COVER"
                result = trader.execute(shadow_id, symbol, close_side, price, 0)
                if result:
                    await redis.delete(pos_key)
                    await redis.lpush(f"shadow:trades:{shadow_id}", json.dumps(result))
                    await redis.ltrim(f"shadow:trades:{shadow_id}", 0, 999)
                    closed = {
                        "shadow_id": shadow_id,
                        "symbol": symbol,
                        "source": "shadow_system",
                        "closed_at": time.time(),
                        **result,
                    }
                    await redis.publish("ch:trade_closed", json.dumps(closed))
                    schedule_save(closed)
            else:
                continue  # Already in correct direction

        # Open new position if none exists
        if not await redis.exists(pos_key):
            open_side = "BUY" if direction == "long" else "SELL_SHORT"
            result = trader.execute(shadow_id, symbol, open_side, price, size_usd)
            if result:
                await redis.set(pos_key, json.dumps({
                    "direction": direction, "price": price,
                    "size_usd": size_usd, "time": time.time(),
                }), ex=86400)


async def report_loop(redis: aioredis.Redis):
    promo = PromotionEngine()
    while True:
        leaderboard = trader.leaderboard()
        await redis.set("shadow:leaderboard", json.dumps(leaderboard), ex=300)

        ready = [e for e in leaderboard if e.get("promotion_ready")]
        best = ready[0] if ready else (leaderboard[0] if leaderboard else None)
        approved = len(ready) > 0
        reason = "promotion criteria met" if approved else (
            f"best shadow {best['shadow_id']}: {best.get('checks', {})}" if best else "no shadow data"
        )
        if best and not approved:
            ok, reason = promo.should_promote(
                {
                    "total_trades": best.get("trades", 0),
                    "sharpe": best.get("sharpe", 0),
                    "win_rate": best.get("win_rate", 0),
                    "max_drawdown": best.get("metrics", {}).get("max_drawdown", 1),
                },
                PORTFOLIO_VALUE,
            )

        await redis.set(
            "system:promotion:status",
            json.dumps({
                "approved": approved,
                "reason": reason,
                "best_shadow_id": best["shadow_id"] if best else None,
                "ready_count": len(ready),
                "leaderboard": leaderboard,
                "updated_at": time.time(),
            }),
            ex=600,
        )

        for entry in ready:
            log.info(
                f"PROMOTION READY: {entry['shadow_id']} "
                f"Sharpe={entry['sharpe']:.2f} WR={entry['win_rate']:.1%}"
            )
        summary = ", ".join(f"{e['shadow_id']} S={e['sharpe']:.2f}" for e in leaderboard)
        log.info(f"Shadow leaderboard: [{summary}] promotion_approved={approved}")
        await asyncio.sleep(300)


async def main():
    log.info("shadow_system starting")
    redis = await aioredis.from_url(REDIS_URL)
    await asyncio.gather(
        _trading_loop(redis),
        report_loop(redis),
    )


async def _trading_loop(redis: aioredis.Redis):
    symbols: list[str] = []
    last_refresh = 0.0

    while True:
        now = time.time()
        if now - last_refresh > SYMBOL_REFRESH_INTERVAL or not symbols:
            symbols = await discover_symbols(redis)
            last_refresh = now
            log.info(f"shadow_system tracking {len(symbols)} symbols")

        for symbol in symbols:
            try:
                await simulate_tick(redis, symbol)
            except Exception as e:
                log.error(f"Shadow tick error {symbol}: {e}")
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
