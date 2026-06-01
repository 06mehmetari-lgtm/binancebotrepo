import asyncio
import aiohttp
import json
import os
import time
import logging
import redis.asyncio as aioredis

log = logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
API_KEY = os.getenv("CRYPTOPANIC_KEY", "")

_DEFAULT_COINS = ["BTC", "ETH", "BNB"]


async def _discover_coins(redis: aioredis.Redis) -> list[str]:
    """Pull active coins from signal + feature keys; fall back to defaults."""
    try:
        sig_keys = await redis.keys("signal:latest:*")
        feat_keys = await redis.keys("features:latest:*")
        coins: set[str] = set()
        for k in list(sig_keys) + list(feat_keys):
            raw = (k.decode() if isinstance(k, bytes) else k).split(":")[-1].upper()
            coin = raw.replace("USDT", "").replace("1000", "")
            if 2 <= len(coin) <= 10 and coin.isalpha():
                coins.add(coin)
        return sorted(coins)[:60] if coins else _DEFAULT_COINS
    except Exception:
        return _DEFAULT_COINS


class CryptoPanicFeed:
    def __init__(self):
        self._redis: aioredis.Redis | None = None

    async def run(self):
        self._redis = await aioredis.from_url(REDIS_URL)
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={API_KEY}&public=true"
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    coin_symbols = await _discover_coins(self._redis)
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        data = await resp.json()
                    items = data.get("results", [])
                    if items:
                        positive_words = ["bullish", "surge", "rally", "buy", "growth", "gain"]
                        negative_words = ["crash", "drop", "fear", "ban", "hack", "scam", "sell"]
                        scores: dict[str, list[float]] = {s: [] for s in coin_symbols}
                        for item in items[:50]:
                            title = item.get("title", "").lower()
                            score = 0.0
                            for w in positive_words:
                                if w in title: score += 0.15
                            for w in negative_words:
                                if w in title: score -= 0.15
                            score = max(-1.0, min(1.0, score))
                            for currency in item.get("currencies", []):
                                code = currency.get("code", "").upper()
                                if code in scores:
                                    scores[code].append(score)
                        for coin, vals in scores.items():
                            if vals:
                                symbol = f"{coin}USDT"
                                avg = sum(vals) / len(vals)
                                payload = {"score": avg, "item_count": len(vals), "time": time.time()}
                                await self._redis.set(
                                    f"sentiment:news:{symbol}", json.dumps(payload), ex=600
                                )
                except Exception as e:
                    log.error(f"CryptoPanic feed error: {e}")
                await asyncio.sleep(60)
