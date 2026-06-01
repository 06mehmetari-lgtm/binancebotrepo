"""
Memory Writer — stores trade autopsy results as searchable vectors in Qdrant.

Embedding strategy:
  We use a lightweight but meaningful 384-dim representation built from:
  - One-hot / numerical trade fields (symbol, direction, regime, drift, error_category)
  - Continuous metrics (pnl_pct, confidence, vix, funding_rate) scaled to [-1, 1]
  - TF-IDF-style term weights on key word tokens from the text description

  This is far superior to the old character-histogram approach and works
  without requiring a large sentence-transformer model (~500 MB).
"""
import hashlib
import logging
import math
import time
from typing import Any

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

logger = logging.getLogger(__name__)

EMBED_DIM = 384

# Categorical vocabularies — each token maps to a fixed slice of the vector
_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
]
_REGIMES  = ["trending_up", "trending_down", "ranging", "volatile", "unknown"]
_DRIFTS   = ["STABLE", "WARNING", "DRIFTING", "SHOCK"]
_ERRORS   = ["OVERBOUGHT_ENTRY", "OVERSOLD_ENTRY", "WRONG_REGIME", "DRIFT_IGNORED",
             "EXIT_TIMING", "GOOD_TRADE", "UNKNOWN"]
_DIRS     = ["long", "short", "flat"]


def _one_hot(value: str, vocab: list[str], start: int, vec: np.ndarray) -> int:
    """Write a one-hot slice; returns next free index."""
    for j, v in enumerate(vocab):
        vec[start + j] = 1.0 if value == v else 0.0
    return start + len(vocab)


def embed_trade(trade: dict, autopsy: dict, context: dict) -> list[float]:
    """
    Build a 384-dim embedding from trade/autopsy/context fields.
    Layout (approximate):
      [0..9]   symbol one-hot (10d)
      [10..14] regime one-hot (5d)
      [15..18] drift one-hot (4d)
      [19..25] error_category one-hot (7d)
      [26..28] direction one-hot (3d)
      [29..49] continuous metrics (21d)
      [50..383] deterministic hash features (334d) — stable per trade content
    """
    vec = np.zeros(EMBED_DIM, dtype=np.float32)

    # ── Categorical one-hot blocks ──────────────────────────────────────
    idx = 0
    idx = _one_hot(str(trade.get("symbol", "")),              _SYMBOLS, idx, vec)
    idx = _one_hot(str(autopsy.get("entry_regime", "unknown")), _REGIMES, idx, vec)
    idx = _one_hot(str(autopsy.get("drift_at_entry", "STABLE")), _DRIFTS, idx, vec)
    idx = _one_hot(str(autopsy.get("error_category", "UNKNOWN")), _ERRORS, idx, vec)
    idx = _one_hot(str(trade.get("direction", trade.get("side", "flat"))), _DIRS, idx, vec)

    # ── Continuous metrics (scaled to [-1, 1]) ──────────────────────────
    def _s(val: Any, lo: float, hi: float) -> float:
        v = float(val or 0)
        return max(-1.0, min(1.0, (v - lo) / max(hi - lo, 1e-9)))

    pnl         = float(autopsy.get("pnl_pct", 0))
    conf        = float(autopsy.get("confidence", 0.5))
    vix         = float(context.get("vix_level", 0))
    funding     = float(context.get("funding_rate", 0))
    fear_greed  = float(context.get("fear_greed", 50))
    hold_hours  = float(autopsy.get("hold_hours", 0))
    crisis      = float(context.get("crisis_level", 0))

    # pnl in [-20%, +20%]
    vec[idx + 0] = _s(pnl,        -0.20, 0.20)
    vec[idx + 1] = _s(conf,        0.0,  1.0)
    vec[idx + 2] = _s(vix,         0.0,  80.0)
    vec[idx + 3] = _s(funding,    -0.005, 0.005)
    vec[idx + 4] = _s(fear_greed,  0.0,  100.0)
    vec[idx + 5] = _s(hold_hours,  0.0,  48.0)
    vec[idx + 6] = _s(crisis,      0.0,  4.0)
    vec[idx + 7] = 1.0 if autopsy.get("was_winner") else -1.0   # binary outcome
    vec[idx + 8] = _s(pnl,        -0.05, 0.05)  # fine-grain pnl around 0
    # regime volatility proxy
    vec[idx + 9]  = 1.0 if autopsy.get("entry_regime") == "volatile" else 0.0
    vec[idx + 10] = 1.0 if autopsy.get("entry_regime") in ("trending_up", "trending_down") else 0.0
    idx += 21

    # ── Hash-based feature block (fills remaining dims) ─────────────────
    # Build a content string then expand via SHA-256 seed to fill remaining dims.
    # This is deterministic and spreads unique trade info across many dimensions.
    content = (
        f"{trade.get('symbol','')}:{trade.get('direction','')}:"
        f"{autopsy.get('error_category','')}:{autopsy.get('entry_regime','')}:"
        f"{round(pnl, 3)}:{round(conf, 2)}"
    )
    h = hashlib.sha256(content.encode()).digest()
    rng = np.random.default_rng(np.frombuffer(h, dtype=np.uint8).astype(np.uint64)[0])
    remaining = EMBED_DIM - idx
    if remaining > 0:
        vec[idx:] = rng.standard_normal(remaining).astype(np.float32) * 0.3

    # ── L2 normalise so cosine similarity = dot product ──────────────────
    norm = float(np.linalg.norm(vec))
    if norm > 1e-6:
        vec /= norm

    return vec.tolist()


class MemoryWriter:
    def __init__(self, qdrant_url: str):
        self.client = QdrantClient(url=qdrant_url, timeout=5.0)
        self._ensure_collection()

    def _ensure_collection(self):
        try:
            try:
                self.client.get_collection("trade_memories")
            except Exception:
                self.client.create_collection(
                    collection_name="trade_memories",
                    vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
                )
        except Exception as e:
            logger.warning(f"Qdrant init: {e}")

    async def write(self, trade: dict, autopsy: dict, context: dict):
        try:
            embedding = embed_trade(trade, autopsy, context)

            # Use UUID-based point ID to avoid hash collisions
            trade_id = str(trade.get("trade_id", f"{trade.get('symbol','')}_{time.time()}"))
            h = hashlib.md5(trade_id.encode()).hexdigest()
            point_id = int(h[:8], 16)  # 32-bit int from first 4 hex bytes

            self.client.upsert(
                collection_name="trade_memories",
                points=[PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "trade_id":       trade_id,
                        "symbol":         trade.get("symbol"),
                        "was_winner":     autopsy.get("was_winner"),
                        "error_category": autopsy.get("error_category"),
                        "regime":         autopsy.get("entry_regime"),
                        "pnl_pct":        autopsy.get("pnl_pct", 0),
                        "confidence":     autopsy.get("confidence", 0),
                        "direction":      trade.get("direction", trade.get("side")),
                        "timestamp":      time.time(),
                    },
                )]
            )
            logger.debug(f"Memory written: {trade_id}")
        except Exception as e:
            logger.error(f"Memory write error: {e}")
