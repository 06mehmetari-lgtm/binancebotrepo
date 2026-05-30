from sentence_transformers import SentenceTransformer
import numpy as np

MODEL_NAME = "all-MiniLM-L6-v2"
_model = None

def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model

def embed(text: str) -> list[float]:
    vec = get_model().encode(text, normalize_embeddings=True)
    return vec.tolist()

def embed_batch(texts: list[str]) -> list[list[float]]:
    vecs = get_model().encode(texts, normalize_embeddings=True, batch_size=32)
    return vecs.tolist()
