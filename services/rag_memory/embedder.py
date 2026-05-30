import numpy as np


class Embedder:
    """Lightweight embedder using sentence-transformers if available, otherwise hash-based fallback."""

    def __init__(self):
        self._model = None
        self._load_model()

    def _load_model(self):
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception:
            self._model = None

    def embed(self, text: str) -> list[float]:
        if self._model:
            vec = self._model.encode(text, normalize_embeddings=True)
            return vec.tolist()
        # Hash-based fallback: deterministic but not semantic
        arr = np.zeros(384)
        for i, ch in enumerate(text[:384]):
            arr[i % 384] += ord(ch) / 1000.0
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr.tolist()
