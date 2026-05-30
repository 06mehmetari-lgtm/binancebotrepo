"""News sentiment agent — reads CryptoPanic + FinBERT scores from Redis."""
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
        try:
            r = _get_redis()
            news_raw = r.get(f"sentiment:news:{symbol}")
            if news_raw:
                news = json.loads(news_raw)
                score = float(news.get("score", 0))
        except Exception:
            pass

        signal = "long" if score > 0.15 else ("short" if score < -0.15 else "flat")
        confidence = min(abs(score) * 2, 1.0)
        return {"agent": "news_agent", "signal": signal, "confidence": confidence,
                "reasoning": {"news_score": score}}
