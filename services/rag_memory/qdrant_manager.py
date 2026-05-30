import os
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
VECTOR_DIM = 384

class QdrantManager:
    def __init__(self):
        self.client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    def create_collection(self, name: str):
        existing = [c.name for c in self.client.get_collections().collections]
        if name not in existing:
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )

    def upsert(self, collection: str, point_id: int, vector: list[float], payload: dict):
        self.client.upsert(
            collection_name=collection,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)]
        )
