"""
RAG Context — Faz 3: Benzer geçmiş durumları debate'e enjekte et.

Debate başlamadan önce Qdrant'tan mevcut piyasa durumuna benzer
geçmiş trade'leri çeker ve formatlı metin bloğu döner.

"Bu durumda geçen sefer ne oldu?" sorusunu LLM'e verir.
Ters mühendislik: kaybeden durumdan nasıl kazanılır öğretir.

Embedding vektörü autopsy/memory_writer.embed_trade ile AYNI layout kullanır
→ cosine similarity gerçekten benzer durumları bulur.
"""

import hashlib
import logging
import os

import numpy as np

log = logging.getLogger(__name__)

QDRANT_URL  = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION  = "trade_memories"
EMBED_DIM   = 384
MIN_SCORE   = 0.50   # düşük benzerlikler anlamsız — bu eşiğin altını at
MAX_AGE_DAYS = 90    # çok eski trade'ler piyasa koşulları değiştiğinden daha az değerli

# Aynı vocab autopsy/memory_writer ile — değiştirme
_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
]
_REGIMES = ["trending_up", "trending_down", "ranging", "volatile", "unknown"]
_DRIFTS  = ["STABLE", "WARNING", "DRIFTING", "SHOCK"]
_ERRORS  = ["OVERBOUGHT_ENTRY", "OVERSOLD_ENTRY", "WRONG_REGIME", "DRIFT_IGNORED",
            "EXIT_TIMING", "GOOD_TRADE", "UNKNOWN"]
_DIRS    = ["long", "short", "flat"]


def _one_hot(value: str, vocab: list, start: int, vec: np.ndarray) -> int:
    for j, v in enumerate(vocab):
        vec[start + j] = 1.0 if value == v else 0.0
    return start + len(vocab)


def _s(val: float, lo: float, hi: float) -> float:
    return max(-1.0, min(1.0, (float(val or 0) - lo) / max(hi - lo, 1e-9)))


def _build_query_vector(
    symbol: str,
    direction: str,
    regime: str,
    drift: str,
    confidence: float,
    vix: float,
    funding: float,
    fear_greed: float,
) -> list[float]:
    """
    Mevcut piyasa durumundan sorgu vektörü oluştur.
    autopsy/memory_writer.embed_trade ile aynı layout:
      [0..9]   symbol one-hot
      [10..14] regime one-hot
      [15..18] drift one-hot
      [19..25] error_category one-hot (UNKNOWN for live query)
      [26..28] direction one-hot
      [29..49] continuous metrics
      [50..383] deterministic hash block
    """
    vec = np.zeros(EMBED_DIM, dtype=np.float32)

    idx = 0
    idx = _one_hot(symbol,    _SYMBOLS, idx, vec)
    idx = _one_hot(regime,    _REGIMES, idx, vec)
    idx = _one_hot(drift,     _DRIFTS,  idx, vec)
    idx = _one_hot("UNKNOWN", _ERRORS,  idx, vec)  # no error known yet
    idx = _one_hot(direction, _DIRS,    idx, vec)

    vec[idx + 0]  = _s(0.0,        -0.20,  0.20)   # pnl unknown
    vec[idx + 1]  = _s(confidence,  0.0,   1.0)
    vec[idx + 2]  = _s(vix,         0.0,   80.0)
    vec[idx + 3]  = _s(funding,    -0.005, 0.005)
    vec[idx + 4]  = _s(fear_greed,  0.0,   100.0)
    vec[idx + 5]  = 0.0   # hold_hours = 0 (henüz açılmadı)
    vec[idx + 6]  = 0.0   # crisis_level
    vec[idx + 7]  = 0.0   # outcome bilinmiyor
    vec[idx + 8]  = _s(0.0, -0.05, 0.05)
    vec[idx + 9]  = 1.0 if regime == "volatile" else 0.0
    vec[idx + 10] = 1.0 if regime in ("trending_up", "trending_down") else 0.0
    idx += 21

    # Deterministik hash bloğu — memory_writer ile aynı
    content = f"{symbol}:{direction}:UNKNOWN:{regime}:0.0:{round(confidence, 2)}"
    h   = hashlib.sha256(content.encode()).digest()
    rng = np.random.default_rng(np.frombuffer(h, dtype=np.uint8).astype(np.uint64)[0])
    remaining = EMBED_DIM - idx
    if remaining > 0:
        vec[idx:] = rng.standard_normal(remaining).astype(np.float32) * 0.3

    norm = float(np.linalg.norm(vec))
    if norm > 1e-6:
        vec /= norm

    return vec.tolist()


def _format_memories(hits: list, symbol: str) -> str:
    """
    Qdrant sonuçlarını LLM'in anlayacağı formatlı metin bloğuna çevir.
    Kazananlar ve kaybedenler ayrı gruplandırılır.
    """
    winners = []
    losers  = []

    for hit in hits:
        p = hit.payload or {}
        sym    = p.get("symbol",         "?")
        dire   = str(p.get("direction",  "?")).upper()
        reg    = p.get("regime",         "?")
        pnl    = float(p.get("pnl_pct",  0)) * 100   # float → yüzde
        conf   = float(p.get("confidence", 0))
        winner = bool(p.get("was_winner", False))
        err    = p.get("error_category", "")
        score  = hit.score

        outcome = f"KÂR %{pnl:+.1f}" if winner else f"ZARAR %{pnl:+.1f}"
        hata    = f" — hata: {err}" if err and err not in ("UNKNOWN", "GOOD_TRADE") else ""
        line    = (
            f"  • {sym} {dire} | {reg} rejim | güven {conf:.0%}"
            f" → {outcome}{hata} (benzerlik {score:.0%})"
        )
        if winner:
            winners.append(line)
        else:
            losers.append(line)

    if not winners and not losers:
        return ""

    parts = [
        "GEÇMİŞTE BENZER DURUMLAR "
        f"(sembol: {symbol} — ters mühendislik rehberi):"
    ]
    if losers:
        parts.append("  ❌ Kaybettiren durumlar — TEKRAR ETME:")
        parts.extend(losers)
    if winners:
        parts.append("  ✅ Kazandıran durumlar — BU KALIPLARI TEKRARLA:")
        parts.extend(winners)

    return "\n".join(parts)


class RAGContext:
    """
    Qdrant'ı doğrudan sorgular (rag_memory servisini bypass eder).
    Senkron Qdrant çağrısı → asyncio.to_thread ile event loop'u bloke etmez.
    """

    def __init__(self):
        self._client = None

    def _client_or_none(self):
        if self._client is not None:
            return self._client
        try:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(url=QDRANT_URL, timeout=2.0)
            return self._client
        except Exception as e:
            log.debug(f"RAGContext: Qdrant bağlantı kurulamadı: {e}")
            return None

    def _search_sync(
        self,
        symbol: str,
        features: dict,
        context: dict,
        limit: int = 3,
    ) -> str:
        """Senkron Qdrant araması — asyncio.to_thread içinden çağrılır."""
        client = self._client_or_none()
        if client is None:
            return ""

        try:
            regime     = str(context.get("regime", features.get("regime", "unknown")) or "unknown")
            drift      = str(context.get("drift_status", features.get("drift_status", "STABLE")) or "STABLE")
            confidence = float(features.get("ml_score") or features.get("confidence") or 0.5)
            vix        = float(context.get("vix_level", 0) or 0)
            funding    = float(context.get("funding_rate", features.get("funding_rate", 0)) or 0)
            fear_greed = float(context.get("fear_greed", features.get("fear_greed", 50)) or 50)

            # Sinyali bilmiyoruz henüz — her iki yönü de kapsayan sorgu
            # "long" kullanmak yerine "flat" ile tarafsız bir vektör oluştur
            vector = _build_query_vector(
                symbol=symbol,
                direction="flat",
                regime=regime,
                drift=drift,
                confidence=confidence,
                vix=vix,
                funding=funding,
                fear_greed=fear_greed,
            )

            results = client.search(
                collection_name=COLLECTION,
                query_vector=vector,
                limit=limit + 3,         # biraz fazla çek, filtrele
                score_threshold=MIN_SCORE,
                with_payload=True,
            )

            if not results:
                return ""

            return _format_memories(results[:limit], symbol)

        except Exception as e:
            log.debug(f"RAGContext._search_sync hata: {e}")
            self._client = None   # bağlantı sıfırla
            return ""


# ── Modül düzeyinde singleton ─────────────────────────────────────────────────
_rag = RAGContext()


async def fetch_similar(
    symbol: str,
    features: dict,
    context: dict,
    limit: int = 3,
) -> str:
    """
    Async wrapper — Qdrant çağrısını thread pool'da çalıştırır.
    Event loop'u bloke etmez. Hata durumunda "" döner.
    """
    import asyncio
    try:
        return await asyncio.to_thread(
            _rag._search_sync, symbol, features, context, limit
        )
    except Exception as e:
        log.debug(f"RAGContext.fetch_similar hata: {e}")
        return ""
