import logging
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)


class MemoryRetriever:
    def __init__(self, qdrant_url: str):
        self.client = QdrantClient(url=qdrant_url)

    def search(self, vector: list[float], collection: str = "trade_memories", limit: int = 5) -> list[dict]:
        try:
            results = self.client.search(collection_name=collection, query_vector=vector, limit=limit)
            return [{"score": float(r.score), "payload": r.payload} for r in results]
        except Exception as e:
            logger.warning(f"Qdrant search error: {e}")
            return []
