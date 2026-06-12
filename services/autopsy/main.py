import asyncio
import json
import logging
import os
import time

import asyncpg
import redis.asyncio as aioredis

from trade_analyzer import TradeAnalyzer
from question_engine import QuestionEngine
from memory_writer import MemoryWriter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://prometheus:password@postgres:5432/prometheus_trading")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")

analyzer = TradeAnalyzer()
question_engine = QuestionEngine()
memory_writer = MemoryWriter(qdrant_url=QDRANT_URL)


async def process_closed_trade(redis: aioredis.Redis, db, trade_data: dict):
    symbol = trade_data.get("symbol", "")
    ctx_raw = await redis.get(f"context:latest:{symbol}")
    ctx = json.loads(ctx_raw) if ctx_raw else {}

    result = analyzer.analyze(trade_data, ctx)
    log.info(f"Autopsy: {symbol} pnl={result['pnl_pct']:.2%} cat={result['error_category']}")

    # Write to memory
    await memory_writer.write(trade_data, result, ctx, redis=redis)

    exit_reason = str(trade_data.get("exit_reason", "") or "")[:200]
    lesson_text = (
        f"{symbol}: {'WIN' if result['was_winner'] else 'LOSS'} "
        f"{result['pnl_pct']:+.2%} — {result['error_category']}"
        + (f" | {exit_reason}" if exit_reason else "")
    )
    await redis.lpush("activity:feed", json.dumps({
        "type": "autopsy",
        "symbol": symbol,
        "title": f"Autopsy {'✓' if result['was_winner'] else '✗'} {symbol}",
        "body": lesson_text,
        "level": "success" if result["was_winner"] else "warning",
        "time": time.time(),
    }))
    await redis.ltrim("activity:feed", 0, 499)

    # Penalize genome if loss
    genome_id = trade_data.get("genome_id")
    if genome_id and not result["was_winner"] and db:
        try:
            await db.execute(
                "UPDATE rule_genomes SET fitness_score = fitness_score - 0.1, updated_at = NOW() WHERE id = $1",
                genome_id
            )
            if result["pnl_pct"] < -0.05:
                await db.execute(
                    "UPDATE rule_genomes SET status = 'PROBATION', updated_at = NOW() WHERE id = $1 AND status = 'ACTIVE'",
                    genome_id
                )
        except Exception as e:
            log.warning(f"DB update error: {e}")


async def main():
    log.info("autopsy starting")
    redis = await aioredis.from_url(REDIS_URL)

    db = None
    try:
        db = await asyncpg.connect(POSTGRES_URL)
    except Exception as e:
        log.warning(f"DB connection failed: {e} — running without DB feedback")

    # Subscribe to trade_closed channel
    pubsub = redis.pubsub()
    await pubsub.subscribe("ch:trade_closed")

    log.info("Listening for closed trades...")
    async for message in pubsub.listen():
        if message is None or message["type"] != "message":
            continue
        try:
            trade_data = json.loads(message["data"])
            await process_closed_trade(redis, db, trade_data)
        except Exception as e:
            log.error(f"Autopsy processing error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
