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
PORTFOLIO_VALUE = float(os.getenv("PORTFOLIO_VALUE", "10000"))
SYMBOL_REFRESH_INTERVAL = 300

# SAR parametreleri (OMS ile aynı eşikler — kağıt trade'de de geçerli)
SAR_CONFIDENCE_THRESHOLD = float(os.getenv("SAR_CONFIDENCE", "0.72"))
SAR_MIN_LOSS_PCT = -1.5   # -%1.5 zararda SAR değerlendirilir


async def discover_symbols(redis: aioredis.Redis) -> list[str]:
    keys = await redis.keys("features:latest:*")
    symbols = [
        (k.decode() if isinstance(k, bytes) else k).split(":")[-1]
        for k in keys
    ]
    return sorted(symbols) if symbols else ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


trader = PaperTrader(initial_capital=PORTFOLIO_VALUE)
SHADOW_IDS = ["SHADOW_A", "SHADOW_B", "SHADOW_C"]


async def simulate_sar_tick(redis: aioredis.Redis, symbol: str, shadow_id: str):
    """Kağıt trade'de SAR simülasyonu: pozisyon yeterli zarardaysa ve karşı sinyal
    yeterli güvene sahipse pozisyonu kapat ve ters yönde yeniden aç."""
    pos_key = f"shadow:positions:{shadow_id}:{symbol}"
    pos_raw = await redis.get(pos_key)
    if not pos_raw:
        return

    pos = json.loads(pos_raw)
    entry_price = float(pos.get("price", 0))
    direction = pos.get("direction", "long")
    if not entry_price:
        return

    ticker_raw = await redis.get(f"binance:ticker:{symbol.lower()}")
    if not ticker_raw:
        return
    td = (json.loads(ticker_raw)).get("data", json.loads(ticker_raw))
    price = float(td.get("b", 0))
    if price <= 0:
        return

    pnl_pct = ((price - entry_price) / entry_price * 100) if direction == "long" \
              else ((entry_price - price) / entry_price * 100)

    if pnl_pct > SAR_MIN_LOSS_PCT:
        return  # Yeterli zarar yok

    sig_raw = await redis.get(f"signal:latest:{symbol}")
    if not sig_raw:
        return
    signal = json.loads(sig_raw)
    new_dir = signal.get("direction", "flat")
    confidence = float(signal.get("confidence", 0))

    if new_dir == direction or new_dir == "flat" or confidence < SAR_CONFIDENCE_THRESHOLD:
        return

    # Kağıt pozisyonu kapat
    close_side = "SELL" if direction == "long" else "BUY_COVER"
    result = trader.execute(shadow_id, symbol, close_side, price, 0)
    if result:
        await redis.delete(pos_key)
        await redis.lpush(f"shadow:trades:{shadow_id}", json.dumps({**result, "sar": True}))
        await redis.ltrim(f"shadow:trades:{shadow_id}", 0, 999)

    # Ters yönde aç
    size_usd = pos.get("size_usd", PORTFOLIO_VALUE * 0.05 * confidence) * 0.8
    open_side = "BUY" if new_dir == "long" else "SELL_SHORT"
    trader.execute(shadow_id, symbol, open_side, price, size_usd)
    ctx_raw = await redis.get(f"context:latest:{symbol}")
    entry_regime = json.loads(ctx_raw).get("regime", "unknown") if ctx_raw else "unknown"
    await redis.set(pos_key, json.dumps({
        "direction": new_dir,
        "price": price,
        "regime": entry_regime,
        "size_usd": size_usd,
        "time": time.time(),
        "is_reversal": True,
    }), ex=86400)
    log.info(f"[SAR shadow] {shadow_id} {symbol}: {direction}→{new_dir} @ {price:.5f} zarar={pnl_pct:+.2f}%")


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
                    # Enrich with entry regime + current agent votes for ML labeling
                    votes_raw = await redis.get(f"agents:verdicts:{symbol}")
                    agent_votes = json.loads(votes_raw) if votes_raw else []
                    await redis.publish("ch:trade_closed", json.dumps({
                        "shadow_id": shadow_id,
                        "symbol": symbol,
                        "regime": pos.get("regime", "unknown"),
                        "agent_votes": agent_votes,
                        **result,
                    }))
            else:
                continue  # Already in correct direction

        # Open new position if none exists
        if not await redis.exists(pos_key):
            # Capture entry regime for labeling when trade closes
            ctx_raw = await redis.get(f"context:latest:{symbol}")
            entry_regime = json.loads(ctx_raw).get("regime", "unknown") if ctx_raw else "unknown"
            open_side = "BUY" if direction == "long" else "SELL_SHORT"
            result = trader.execute(shadow_id, symbol, open_side, price, size_usd)
            if result:
                await redis.set(pos_key, json.dumps({
                    "direction": direction, "price": price,
                    "regime": entry_regime,
                    "size_usd": size_usd, "time": time.time(),
                }), ex=86400)


async def report_loop(redis: aioredis.Redis):
    while True:
        leaderboard = trader.leaderboard()
        await redis.set("shadow:leaderboard", json.dumps(leaderboard), ex=300)
        for entry in leaderboard:
            if entry["promotion_ready"]:
                log.info(
                    f"PROMOTION READY: {entry['shadow_id']} "
                    f"Sharpe={entry['sharpe']:.2f} WR={entry['win_rate']:.1%}"
                )
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
                # SAR simülasyonu: her shadow_id için ayrı kontrol
                for sid in SHADOW_IDS:
                    await simulate_sar_tick(redis, symbol, sid)
            except Exception as e:
                log.error(f"Shadow tick error {symbol}: {e}")
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
