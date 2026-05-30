"""
FinBERT news sentiment analyzer.
Reads from Redis news queue, writes scored sentiments back to Redis.
"""
import json
import logging
import os
import time
import asyncio
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        try:
            from transformers import pipeline
            _pipeline = pipeline(
                "text-classification",
                model="ProsusAI/finbert",
                device=-1,   # CPU
                truncation=True,
                max_length=512,
            )
            logger.info("FinBERT loaded")
        except Exception as e:
            logger.warning(f"FinBERT unavailable ({e}), using keyword fallback")
            _pipeline = "fallback"
    return _pipeline


def _keyword_score(text: str) -> float:
    pos = ["bullish", "surge", "rally", "gain", "buy", "growth", "positive", "up"]
    neg = ["bearish", "crash", "drop", "sell", "fear", "loss", "negative", "down", "ban"]
    t = text.lower()
    score = sum(0.15 for w in pos if w in t) - sum(0.15 for w in neg if w in t)
    return max(-1.0, min(1.0, score))


def analyze_text(text: str) -> dict:
    pipe = _get_pipeline()
    if pipe == "fallback" or pipe is None:
        score = _keyword_score(text)
        label = "positive" if score > 0 else ("negative" if score < 0 else "neutral")
        return {"label": label, "score": abs(score), "compound": score}
    try:
        result = pipe(text[:512])[0]
        label = result["label"].lower()
        raw_score = float(result["score"])
        compound = raw_score if label == "positive" else (-raw_score if label == "negative" else 0.0)
        return {"label": label, "score": raw_score, "compound": compound}
    except Exception as e:
        logger.error(f"FinBERT inference error: {e}")
        return {"label": "neutral", "score": 0.5, "compound": 0.0}


class FinBERTAnalyzer:
    def __init__(self):
        self._redis: aioredis.Redis | None = None

    async def run(self):
        self._redis = await aioredis.from_url(REDIS_URL)
        # Pre-load model
        await asyncio.get_event_loop().run_in_executor(None, _get_pipeline)
        logger.info("FinBERT analyzer ready, listening for news queue")
        while True:
            try:
                item = await self._redis.blpop("news:analyze_queue", timeout=5)
                if item:
                    data = json.loads(item[1])
                    text = data.get("text", "")
                    symbol = data.get("symbol", "BTCUSDT")
                    if text:
                        result = await asyncio.get_event_loop().run_in_executor(
                            None, analyze_text, text
                        )
                        current_raw = await self._redis.get(f"sentiment:finbert:{symbol}")
                        current = json.loads(current_raw) if current_raw else {"compound": 0.0, "count": 0}
                        n = current.get("count", 0)
                        avg = (current.get("compound", 0) * n + result["compound"]) / (n + 1)
                        await self._redis.set(f"sentiment:finbert:{symbol}", json.dumps({
                            "compound": avg, "count": n + 1, "time": time.time()
                        }), ex=3600)
            except Exception as e:
                logger.error(f"FinBERT loop error: {e}")
