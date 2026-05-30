import asyncio
import logging
import os
import json

import redis.asyncio as aioredis

from embedder import Embedder
from qdrant_manager import QdrantManager
from memory_retriever import MemoryRetriever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")

embedder = Embedder()
qdrant_manager = QdrantManager(qdrant_url=QDRANT_URL)
retriever = MemoryRetriever(qdrant_url=QDRANT_URL)


async def handle_memory_request(redis: aioredis.Redis, request: dict) -> list[dict]:
    query = request.get("query", "")
    symbol = request.get("symbol", "")
    limit = int(request.get("limit", 5))

    full_query = f"{symbol} {query}".strip()
    embedding = embedder.embed(full_query)
    results = retriever.search(embedding, collection="trade_memories", limit=limit)
    return results


async def main():
    log.info("rag_memory starting")
    redis = await aioredis.from_url(REDIS_URL)

    # Initialize Qdrant collection
    try:
        qdrant_manager.ensure_collection("trade_memories", vector_size=384)
        log.info("Qdrant collection ready")
    except Exception as e:
        log.warning(f"Qdrant init warning: {e}")

    # Listen for memory retrieval requests
    while True:
        item = await redis.blpop("rag:requests", timeout=5)
        if not item:
            continue
        try:
            request = json.loads(item[1])
            results = await handle_memory_request(redis, request)
            response_key = f"rag:response:{request.get('request_id', 'unknown')}"
            await redis.set(response_key, json.dumps(results), ex=30)
        except Exception as e:
            log.error(f"RAG memory error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
