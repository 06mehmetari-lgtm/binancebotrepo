import logging
import time
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

logger = logging.getLogger(__name__)


class MemoryWriter:
    def __init__(self, qdrant_url: str):
        self.client = QdrantClient(url=qdrant_url)
        self._ensure_collection()

    def _ensure_collection(self):
        try:
            from qdrant_client.models import Distance, VectorParams
            try:
                self.client.get_collection("trade_memories")
            except Exception:
                self.client.create_collection(
                    collection_name="trade_memories",
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                )
        except Exception as e:
            logger.warning(f"Qdrant init: {e}")

    async def write(self, trade: dict, autopsy: dict, context: dict):
        text = (
            f"symbol={trade.get('symbol', '')} side={trade.get('side', '')} "
            f"result={'WIN' if autopsy.get('was_winner') else 'LOSS'} "
            f"pnl={autopsy.get('pnl_pct', 0):.3f} "
            f"regime={autopsy.get('entry_regime', '')} "
            f"error={autopsy.get('error_category', '')} "
            f"drift={autopsy.get('drift_at_entry', '')} "
            f"confidence={autopsy.get('confidence', 0):.2f}"
        )
        embedding = self._embed(text)
        point_id = abs(hash(str(trade.get("trade_id", time.time())))) % (2**31)
        try:
            self.client.upsert(
                collection_name="trade_memories",
                points=[PointStruct(
                    id=point_id, vector=embedding,
                    payload={
                        "symbol": trade.get("symbol"),
                        "was_winner": autopsy.get("was_winner"),
                        "error_category": autopsy.get("error_category"),
                        "regime": autopsy.get("entry_regime"),
                        "pnl_pct": autopsy.get("pnl_pct", 0),
                        "time": time.time(),
                    }
                )]
            )
        except Exception as e:
            logger.error(f"Memory write error: {e}")

    def _embed(self, text: str) -> list[float]:
        arr = np.zeros(384)
        for i, ch in enumerate(text[:384]):
            arr[i % 384] += ord(ch) / 1000.0
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr.tolist()
