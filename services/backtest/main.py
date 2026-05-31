"""
Backtest service — continuous full-universe mode (default).

Processes all TOP_N symbols in chunks 24/7; stores per-symbol history + AI lessons.
Legacy one-shot mode: BACKTEST_MODE=oneshot
"""
import asyncio
import logging
import os

import redis.asyncio as aioredis

from backtest_engine import BacktestEngine
from chunk_runner import continuous_loop, push_log, run_one_chunk

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
PORTFOLIO_VALUE = float(os.getenv("PORTFOLIO_VALUE", "10000"))

engine = BacktestEngine(initial_capital=PORTFOLIO_VALUE)


async def main():
    redis = await aioredis.from_url(REDIS_URL)

    # Continuous 24/7 chunk scanner (full universe)
    results_raw = await redis.get("backtest:results")
    if not results_raw:
        await push_log(redis, "İlk evren taraması başlıyor...")
        try:
            await run_one_chunk(redis, engine)
        except Exception as e:
            log.error(f"Initial chunk failed: {e}")

    await continuous_loop(redis, engine)


if __name__ == "__main__":
    asyncio.run(main())
