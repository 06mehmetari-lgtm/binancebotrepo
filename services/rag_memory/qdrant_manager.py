import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

logger = logging.getLogger(__name__)


class QdrantManager:
    def __init__(self, qdrant_url: str):
        self.client = QdrantClient(url=qdrant_url)

    def ensure_collection(self, name: str, vector_size: int = 384):
        try:
            self.client.get_collection(name)
        except Exception:
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            logger.info(f"Created Qdrant collection: {name}")

    def upsert(self, collection: str, point_id: int, vector: list[float], payload: dict):
        self.client.upsert(
            collection_name=collection,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)]
        )

    def search(self, collection: str, vector: list[float], limit: int = 5) -> list[dict]:
        results = self.client.search(collection_name=collection, query_vector=vector, limit=limit)
        return [{"score": r.score, "payload": r.payload} for r in results]
