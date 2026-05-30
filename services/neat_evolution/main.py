import asyncio
import json
import logging
import os

import redis.asyncio as aioredis

from neat_engine import NEATTradingEngine
from genome_manager import GenomeManager
from rule_lifecycle import RuleLifecycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
POSTGRES_URL = os.getenv("POSTGRES_URL", "")
TIMESCALE_URL = os.getenv("TIMESCALE_URL", "")
SYMBOLS_RAW = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
SYMBOLS = [s.strip() for s in SYMBOLS_RAW.split(",") if s.strip()]

EVOLUTION_INTERVAL = 3 * 3600
GENERATIONS = 30


async def evolution_cycle(redis: aioredis.Redis, gm: GenomeManager):
    for symbol in SYMBOLS:
        log.info(f"Starting NEAT evolution: {symbol}")
        engine = NEATTradingEngine(db_url=TIMESCALE_URL or None, symbol=symbol)
        await engine.load_training_data()
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, engine.run, GENERATIONS
            )
            result["symbol"] = symbol
            await redis.set(f"neat:best_genome:{symbol}", json.dumps(result), ex=86400)
            await redis.lpush("neat:evolution_log", json.dumps(result))
            await redis.ltrim("neat:evolution_log", 0, 99)
            if POSTGRES_URL:
                await gm.save(result)
            log.info(f"NEAT [{symbol}] fitness={result['fitness']:.4f} nodes={result['nodes']}")
        except Exception as e:
            log.error(f"NEAT error [{symbol}]: {e}")


async def main():
    log.info("neat_evolution starting")
    redis = await aioredis.from_url(REDIS_URL)
    gm = GenomeManager(POSTGRES_URL)
    if POSTGRES_URL:
        await gm.connect()
    while True:
        await evolution_cycle(redis, gm)
        log.info(f"Next evolution in {EVOLUTION_INTERVAL}s")
        await asyncio.sleep(EVOLUTION_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
