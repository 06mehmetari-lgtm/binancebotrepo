import os
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
import hashlib, json

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION = "trade_memory"

class MemoryWriter:
    def __init__(self):
        self.client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    def write(self, trade_analysis: dict, embedding: list[float]):
        point_id = int(hashlib.md5(json.dumps(trade_analysis, sort_keys=True).encode()).hexdigest(), 16) % (2**31)
        self.client.upsert(
            collection_name=COLLECTION,
            points=[PointStruct(id=point_id, vector=embedding, payload=trade_analysis)]
        )
