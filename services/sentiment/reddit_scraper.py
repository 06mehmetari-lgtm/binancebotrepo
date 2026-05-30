import asyncio
import json
import logging
import os
import time
import praw
import redis.asyncio as aioredis

log = logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

COIN_KEYWORDS = {
    "BTCUSDT": ["bitcoin", "btc", "satoshi"],
    "ETHUSDT": ["ethereum", "eth", "ether"],
    "BNBUSDT": ["bnb", "binance coin"],
}
SUBREDDITS = ["Bitcoin", "CryptoCurrency", "ethtrader", "CryptoMarkets"]


class RedditScraper:
    def __init__(self):
        self.reddit = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent=os.getenv("REDDIT_USER_AGENT", "prometheus/1.0"),
        )
        self._redis: aioredis.Redis | None = None

    async def run(self):
        self._redis = await aioredis.from_url(REDIS_URL)
        while True:
            try:
                await asyncio.get_event_loop().run_in_executor(None, self._fetch_and_score)
            except Exception as e:
                log.error(f"Reddit scraper error: {e}")
            await asyncio.sleep(300)

    def _fetch_and_score(self):
        scores: dict[str, list[float]] = {s: [] for s in COIN_KEYWORDS}
        try:
            sub = self.reddit.subreddit("+".join(SUBREDDITS))
            for post in sub.new(limit=100):
                text = f"{post.title} {getattr(post, 'selftext', '')}".lower()
                compound = self._simple_sentiment(text)
                weight = max(1, post.score / 10)
                for symbol, keywords in COIN_KEYWORDS.items():
                    if any(kw in text for kw in keywords):
                        scores[symbol].append(compound * weight)
        except Exception as e:
            log.error(f"Reddit fetch error: {e}")
            return

        loop = asyncio.new_event_loop()
        try:
            for symbol, vals in scores.items():
                if vals:
                    avg = sum(vals) / len(vals)
                    payload = {"score": avg, "post_count": len(vals), "time": time.time()}
                    loop.run_until_complete(
                        self._redis.set(f"sentiment:reddit:{symbol}", json.dumps(payload), ex=600)
                    )
        finally:
            loop.close()

    def _simple_sentiment(self, text: str) -> float:
        """Lightweight VADER-style keyword scoring (no external dependency)."""
        bullish = ["bullish", "moon", "buy", "pump", "rally", "surge", "ath", "breakout", "hodl"]
        bearish = ["bearish", "crash", "sell", "dump", "drop", "bear", "collapse", "rekt", "fear"]
        score = 0.0
        for w in bullish:
            if w in text:
                score += 0.1
        for w in bearish:
            if w in text:
                score -= 0.1
        return max(-1.0, min(1.0, score))
