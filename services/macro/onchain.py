import asyncio
import aiohttp
import json
import logging
import os
import time
import redis.asyncio as aioredis

log = logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
ETHERSCAN_KEY = os.getenv("ETHERSCAN_KEY", "")


class OnChainFeed:
    def __init__(self):
        self._redis: aioredis.Redis | None = None

    async def run(self):
        self._redis = await aioredis.from_url(REDIS_URL)
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    await self._fetch_gas(session)
                    await self._fetch_btc_dominance(session)
                except Exception as e:
                    log.error(f"On-chain fetch error: {e}")
                await asyncio.sleep(60)

    async def _fetch_gas(self, session: aiohttp.ClientSession):
        if not ETHERSCAN_KEY:
            return
        url = (f"https://api.etherscan.io/api?module=gastracker"
               f"&action=gasoracle&apikey={ETHERSCAN_KEY}")
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
        result = data.get("result", {})
        if result:
            payload = {
                "safe_gas": result.get("SafeGasPrice"),
                "propose_gas": result.get("ProposeGasPrice"),
                "fast_gas": result.get("FastGasPrice"),
                "time": time.time(),
            }
            await self._redis.set("onchain:eth_gas", json.dumps(payload), ex=120)

    async def _fetch_btc_dominance(self, session: aiohttp.ClientSession):
        url = "https://api.coingecko.com/api/v3/global"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
            dominance = data.get("data", {}).get("market_cap_percentage", {}).get("btc", 50)
            payload = {"btc_dominance": dominance / 100, "time": time.time()}
            await self._redis.set("macro:btc_dominance", json.dumps(payload), ex=3600)
        except Exception as e:
            log.debug(f"BTC dominance fetch: {e}")
