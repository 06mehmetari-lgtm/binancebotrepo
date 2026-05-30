import asyncio
import aiohttp
import json
import os
import time
import logging
import redis.asyncio as aioredis

log = logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")


class FearGreedIndex:
    def __init__(self):
        self._redis: aioredis.Redis | None = None

    async def run(self):
        self._redis = await aioredis.from_url(REDIS_URL)
        url = "https://api.alternative.me/fng/?limit=1"
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        data = await resp.json()
                        entry = data["data"][0]
                        value = int(entry["value"])
                        classification = entry["value_classification"]
                        payload = {
                            "value": value,
                            "classification": classification,
                            "time": time.time(),
                        }
                        await self._redis.set("sentiment:fear_greed", json.dumps(payload), ex=7200)
                        log.info(f"Fear & Greed: {value} ({classification})")
                except Exception as e:
                    log.error(f"Fear & Greed fetch error: {e}")
                await asyncio.sleep(3600)
