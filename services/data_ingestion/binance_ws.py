"""
Binance WebSocket Manager — Redis-backed, auto-reconnecting.
Streams: aggTrade, depth20@100ms, kline_1m, bookTicker for all configured symbols.
"""

import asyncio
import json
import logging
import os
import time
import websockets
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

BASE_FUTURES_URL = "wss://fstream.binance.com/stream"

class BinanceWebSocketManager:
    def __init__(self, redis_url: str, symbols: list[str], on_message=None):
        self.redis_url = redis_url
        self.symbols = [s.lower() for s in symbols]
        self.on_message = on_message
        self.redis: aioredis.Redis | None = None
        self._running = False
        self._reconnect_delay = 1
        self._max_delay = 60
        self._msg_count = 0
        self._last_heartbeat = 0.0

    def _build_url(self) -> str:
        streams = []
        for s in self.symbols:
            streams += [f"{s}@depth20@100ms", f"{s}@aggTrade", f"{s}@kline_1m", f"{s}@bookTicker"]
        return f"{BASE_FUTURES_URL}?streams={'/'.join(streams)}"

    async def connect(self):
        self.redis = await aioredis.from_url(self.redis_url)
        self._running = True
        while self._running:
            try:
                await self._run_connection()
                self._reconnect_delay = 1
            except Exception as e:
                logger.error(f"WebSocket error: {e}, retrying in {self._reconnect_delay}s")
                await self._set_status("DISCONNECTED", self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_delay)

    async def _run_connection(self):
        url = self._build_url()
        logger.info(f"Connecting to Binance WS: {len(self.symbols)} symbols")
        async with websockets.connect(url, ping_interval=20, ping_timeout=10, max_size=10 * 1024 * 1024) as ws:
            await self._set_status("CONNECTED", 0)
            logger.info("WebSocket connected ✅")
            self._reconnect_delay = 1
            async for raw in ws:
                await self._process(raw)

    async def _process(self, raw: str):
        recv_ms = time.time() * 1000
        # Refresh the CONNECTED heartbeat every 20 seconds so the key's TTL stays alive
        now = recv_ms / 1000
        if now - self._last_heartbeat >= 20:
            await self._set_status("CONNECTED", 0)
            self._last_heartbeat = now
        try:
            data = json.loads(raw)
            stream = data.get("stream", "")
            payload = data.get("data", data)
            event_ms = payload.get("E", recv_ms)
            latency = recv_ms - event_ms
            quality = max(0, min(100, int(100 - latency / 10)))

            symbol = payload.get("s", "").upper()
            event_type = payload.get("e", stream)

            enriched = {"data": payload, "recv_ms": recv_ms, "latency_ms": latency, "quality": quality}

            if event_type == "depthUpdate" or "depth" in stream:
                key = f"binance:ob:{symbol.lower()}"
            elif event_type == "aggTrade":
                key = f"binance:trade:{symbol.lower()}"
            elif event_type == "kline":
                key = f"binance:kline:{symbol.lower()}"
            elif event_type == "bookTicker":
                key = f"binance:ticker:{symbol.lower()}"
                await self.redis.set(key, json.dumps(enriched), ex=10)
                if self.on_message:
                    await self.on_message(stream, payload, quality)
                return
            else:
                key = f"binance:raw:{stream}"

            await self.redis.lpush(key, json.dumps(enriched))
            await self.redis.ltrim(key, 0, 999)

            if quality < 50:
                logger.warning(f"Low quality data: {stream} latency={latency:.0f}ms")

            if self.on_message:
                await self.on_message(stream, payload, quality)

        except Exception as e:
            logger.error(f"Message processing error: {e}")

    async def _set_status(self, status: str, reconnect_delay: float):
        if self.redis:
            # CONNECTED key expires in 45s — goes stale if process crashes without disconnect
            # DISCONNECTED key persists for 5 minutes
            ttl = 45 if status == "CONNECTED" else 300
            await self.redis.set("ws:status", json.dumps({
                "status": status,
                "time": time.time(),
                "reconnect_delay": reconnect_delay,
                "symbols": len(self.symbols),
            }), ex=ttl)

    async def stop(self):
        self._running = False
