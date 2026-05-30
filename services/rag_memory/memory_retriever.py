import os
from qdrant_client import QdrantClient
from qdrant_client.models import Filter

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))

class MemoryRetriever:
    def __init__(self):
        self.client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    def search(self, collection: str, query_vector: list[float], top_k: int = 5) -> list[dict]:
        results = self.client.search(
            collection_name=collection,
            query_vector=query_vector,
            limit=top_k,
        )
        return [{"score": r.score, "payload": r.payload} for r in results]
