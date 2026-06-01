"""News sentiment agent — Groq AI analizi + CryptoPanic + FinBERT fallback."""
import json
import os
import redis

_r = None

def _get_redis():
    global _r
    if _r is None:
        _r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True)
    return _r


class NewsAgent:
    def analyze(self, context: dict) -> dict:
        symbol = context.get("symbol", "BTCUSDT")
        score = 0.0
        signal = "flat"
        confidence = 0.3
        reasoning = ""

        try:
            r = _get_redis()

            # Önce Groq AI analizi (GroqNewsScanner tarafından yazılır)
            groq_raw = r.get(f"news:groq:{symbol}")
            if groq_raw:
                g = json.loads(groq_raw)
                score      = float(g.get("score", 0))
                confidence = min(float(g.get("confidence", 0.3)), 0.95)
                signal     = g.get("signal", "flat")
                reasoning  = g.get("summary") or g.get("key_factor") or ""
                return {
                    "agent": "news_agent",
                    "signal": signal,
                    "confidence": confidence,
                    "reasoning": reasoning,
                }

            # Fallback: manuel CryptoPanic + FinBERT skoru
            news_raw = r.get(f"sentiment:news:{symbol}")
            if news_raw:
                news = json.loads(news_raw)
                score = float(news.get("score", 0))
                confidence = min(abs(score) * 2, 0.6)

        except Exception:
            pass

        signal = "long" if score > 0.15 else ("short" if score < -0.15 else "flat")
        return {
            "agent": "news_agent",
            "signal": signal,
            "confidence": confidence,
            "reasoning": reasoning or f"Haber skoru: {score:.2f}",
        }
