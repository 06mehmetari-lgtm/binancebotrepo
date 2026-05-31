"""
Crypto-specific signals: funding rate, open interest, long/short ratio, liquidations.
All free from Binance Futures API. Writes to Redis.
"""

import asyncio
import json
import logging
import time
import httpx
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

FUTURES_BASE = "https://fapi.binance.com"


class CryptoSignalCollector:
    def __init__(self, redis_url: str, symbols: list[str]):
        self.symbols = [s.upper() for s in symbols]
        self.redis_url = redis_url
        self.redis: aioredis.Redis | None = None

    async def start(self):
        self.redis = await aioredis.from_url(self.redis_url)
        await asyncio.gather(
            self._funding_loop(),
            self._oi_loop(),
            self._ls_ratio_loop(),
            self._liquidation_loop(),
        )

    async def _funding_loop(self):
        sem = asyncio.Semaphore(25)

        async def _one(symbol: str, client: httpx.AsyncClient):
            async with sem:
                resp = await client.get(
                    f"{FUTURES_BASE}/fapi/v1/fundingRate",
                    params={"symbol": symbol, "limit": 1},
                )
                data = resp.json()
                if data:
                    rate = float(data[0]["fundingRate"])
                    await self.redis.set(
                        f"funding:{symbol}",
                        json.dumps({"rate": rate, "annualized": rate * 3 * 365, "time": time.time()}),
                        ex=3600,
                    )

        while True:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    await asyncio.gather(
                        *[_one(s, client) for s in self.symbols],
                        return_exceptions=True,
                    )
            except Exception as e:
                logger.error(f"Funding rate error: {e}")
            await asyncio.sleep(900)

    async def _oi_loop(self):
        sem = asyncio.Semaphore(30)

        async def _one(symbol: str, client: httpx.AsyncClient):
            async with sem:
                resp = await client.get(
                    f"{FUTURES_BASE}/fapi/v1/openInterest",
                    params={"symbol": symbol},
                )
                data = resp.json()
                oi = float(data["openInterest"])
                prev_raw = await self.redis.get(f"oi:{symbol}")
                prev_oi = json.loads(prev_raw)["oi"] if prev_raw else oi
                change_pct = (oi - prev_oi) / prev_oi * 100 if prev_oi else 0
                await self.redis.set(
                    f"oi:{symbol}",
                    json.dumps({"oi": oi, "oi_change_pct": change_pct, "time": time.time()}),
                    ex=300,
                )

        while True:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    await asyncio.gather(
                        *[_one(s, client) for s in self.symbols],
                        return_exceptions=True,
                    )
            except Exception as e:
                logger.error(f"Open interest error: {e}")
            await asyncio.sleep(60)

    async def _ls_ratio_loop(self):
        sem = asyncio.Semaphore(20)

        async def _one(symbol: str, client: httpx.AsyncClient):
            async with sem:
                resp = await client.get(
                    f"{FUTURES_BASE}/futures/data/globalLongShortAccountRatio",
                    params={"symbol": symbol, "period": "5m", "limit": 1},
                )
                data = resp.json()
                if data:
                    await self.redis.set(
                        f"ls_ratio:{symbol}",
                        json.dumps({
                            "ls_ratio": float(data[0]["longShortRatio"]),
                            "long_pct": float(data[0]["longAccount"]),
                            "short_pct": float(data[0]["shortAccount"]),
                            "time": time.time(),
                        }),
                        ex=600,
                    )

        while True:
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    await asyncio.gather(
                        *[_one(s, client) for s in self.symbols],
                        return_exceptions=True,
                    )
            except Exception as e:
                logger.error(f"Long/short ratio error: {e}")
            await asyncio.sleep(300)

    async def _liquidation_loop(self):
        import websockets
        symbols_stream = "/".join(f"{s.lower()}@forceOrder" for s in self.symbols)
        url = f"wss://fstream.binance.com/stream?streams={symbols_stream}"
        while True:
            try:
                async with websockets.connect(url) as ws:
                    async for raw in ws:
                        data = json.loads(raw)
                        order = data.get("data", {}).get("o", {})
                        if order:
                            value = float(order.get("q", 0)) * float(order.get("p", 0))
                            if value > 50_000:
                                await self.redis.lpush("liquidations:large", json.dumps({
                                    "symbol": order.get("s"),
                                    "side": order.get("S"),
                                    "value_usdt": value,
                                    "price": order.get("p"),
                                    "time": time.time()
                                }))
                                await self.redis.ltrim("liquidations:large", 0, 499)
            except Exception as e:
                logger.error(f"Liquidation WS error: {e}")
                await asyncio.sleep(5)
