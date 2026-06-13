import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from embedder import Embedder
from qdrant_manager import QdrantManager
from memory_retriever import MemoryRetriever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")

embedder: Embedder | None = None
qdrant_manager: QdrantManager | None = None
retriever: MemoryRetriever | None = None


def _ensure_clients() -> None:
    global embedder, qdrant_manager, retriever
    if embedder is None:
        embedder = Embedder()
    if qdrant_manager is None:
        qdrant_manager = QdrantManager(qdrant_url=QDRANT_URL)
    if retriever is None:
        retriever = MemoryRetriever(qdrant_url=QDRANT_URL)


async def heartbeat_loop(redis: aioredis.Redis) -> None:
    while True:
        await redis.set("system:heartbeat:rag_memory", str(time.time()), ex=120)
        await asyncio.sleep(30)


async def handle_memory_request(request: dict) -> list[dict]:
    _ensure_clients()
    query = request.get("query", "")
    symbol = request.get("symbol", "")
    limit = int(request.get("limit", 5))

    full_query = f"{symbol} {query}".strip()
    embedding = embedder.embed(full_query)
    results = retriever.search(embedding, collection="trade_memories", limit=limit)
    return results


async def main():
    log.info("rag_memory starting (redis=%s)", REDIS_URL.split("@")[-1])
    redis = await aioredis.from_url(REDIS_URL)
    await redis.ping()
    log.info("Redis connected")

    asyncio.create_task(heartbeat_loop(redis))
    await redis.set("system:heartbeat:rag_memory", str(time.time()), ex=120)

    _ensure_clients()
    try:
        qdrant_manager.ensure_collection("trade_memories", vector_size=384)
        log.info("Qdrant collection ready")
    except Exception as e:
        log.warning("Qdrant init warning: %s", e)

    while True:
        item = await redis.blpop("rag:requests", timeout=5)
        await redis.set("system:heartbeat:rag_memory", str(time.time()), ex=120)
        if not item:
            continue
        try:
            request = json.loads(item[1])
            results = await handle_memory_request(request)
            response_key = f"rag:response:{request.get('request_id', 'unknown')}"
            await redis.set(response_key, json.dumps(results), ex=30)
        except Exception as e:
            log.error("RAG memory error: %s", e)


if __name__ == "__main__":
    asyncio.run(main())
