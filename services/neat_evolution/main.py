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
NEAT_MAX_SYMBOLS = int(os.getenv("NEAT_MAX_SYMBOLS", "150"))
NEAT_CONCURRENCY = int(os.getenv("NEAT_CONCURRENCY", "4"))


async def discover_symbols(redis: aioredis.Redis) -> list[str]:
    keys = await redis.keys("features:latest:*")
    symbols = [
        (k.decode() if isinstance(k, bytes) else k).split(":")[-1]
        for k in keys
    ]
    return sorted(symbols) if symbols else ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

EVOLUTION_INTERVAL = 3 * 3600
GENERATIONS = 30


async def evolution_cycle(redis: aioredis.Redis, gm: GenomeManager):
    all_symbols = await discover_symbols(redis)
    # Limit to top N to keep evolution tractable
    symbols = all_symbols[:NEAT_MAX_SYMBOLS]
    log.info(f"neat_evolution: {len(symbols)}/{len(all_symbols)} symbols, {NEAT_CONCURRENCY} parallel workers")

    results_list: list[dict] = []
    sem = asyncio.Semaphore(NEAT_CONCURRENCY)

    async def evolve_one(symbol: str):
        async with sem:
            engine = NEATTradingEngine(db_url=TIMESCALE_URL or None, symbol=symbol)
            await engine.load_training_data()
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, engine.run, GENERATIONS
                )
                result["symbol"] = symbol
                results_list.append(result)
                await redis.set(f"neat:best_genome:{symbol}", json.dumps(result), ex=86400)
                await redis.lpush("neat:evolution_log", json.dumps(result))
                await redis.ltrim("neat:evolution_log", 0, 999)
                if POSTGRES_URL:
                    await gm.save(result)
                log.info(f"NEAT [{symbol}] fitness={result['fitness']:.4f} nodes={result['nodes']}")
                # Publish live signal from best genome on current market features
                feat_raw = await redis.get(f"features:latest:{symbol}")
                if feat_raw and engine._best_genome is not None:
                    import json as _json
                    live_features = _json.loads(feat_raw)
                    signal = engine.predict_signal(live_features)
                    await redis.set(f"neat:signal:{symbol}", _json.dumps(signal), ex=EVOLUTION_INTERVAL + 600)
                    log.info(f"NEAT [{symbol}] live signal: {signal['direction']} conf={signal['confidence']:.3f}")
            except Exception as e:
                log.error(f"NEAT error [{symbol}]: {e}")

    await asyncio.gather(*[evolve_one(s) for s in symbols])

    if results_list:
        import time as _time
        best = max(results_list, key=lambda r: r.get("fitness", 0))
        stats = {
            "generation": GENERATIONS,
            "best_fitness": best.get("fitness", 0),
            "genome_count": sum(r.get("genome_count", 0) for r in results_list),
            "species_count": best.get("species_count", 1),
            "symbol_count": len(results_list),
            "timestamp": _time.time(),
        }
        await redis.set("neat:stats", json.dumps(stats), ex=86400)
        log.info(f"neat:stats written — best_fitness={stats['best_fitness']:.4f} symbols={stats['symbol_count']}")


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
