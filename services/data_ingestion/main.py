import asyncio
import json
import logging
import os
import time

import httpx
import redis.asyncio as aioredis

from binance_ws import BinanceWebSocketManager
from order_book import LocalOrderBook
from crypto_signals import CryptoSignalCollector
from symbol_discovery import fetch_top_symbols

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOLS_RAW = os.getenv("SYMBOLS", "AUTO")
TOP_N = int(os.getenv("TOP_SYMBOLS", "500"))
# Each symbol uses 4 streams; Binance limit is 1024 per connection → max 256 symbols per WS
WS_BATCH_SIZE = 200

order_books: dict[str, LocalOrderBook] = {}


def resolve_symbols() -> list[str]:
    if SYMBOLS_RAW.strip().upper() == "AUTO":
        return fetch_top_symbols(TOP_N)
    return [s.strip() for s in SYMBOLS_RAW.split(",") if s.strip()]


async def handle_ws_message(stream: str, payload: dict, quality: int):
    symbol = payload.get("s", "").upper()
    event_type = payload.get("e", "")
    if event_type == "depthUpdate" and symbol in order_books:
        order_books[symbol].process_event(payload)


async def init_order_books(symbols: list[str]):
    # Initialize order books in parallel batches to speed up startup
    async def init_one(sym):
        try:
            ob = LocalOrderBook(sym)
            await ob.initialize()
            order_books[sym] = ob
        except Exception as e:
            log.warning(f"Order book init failed for {sym}: {e}")

    batch_size = 20
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        await asyncio.gather(*[init_one(s) for s in batch])
        log.info(f"Order books: {i + len(batch)}/{len(symbols)} initialized")


async def ob_snapshot_loop(redis: aioredis.Redis):
    """Publish full 20-level order book snapshots for feature_engine (all symbols)."""
    while True:
        published = 0
        for sym, ob in list(order_books.items()):
            try:
                snap = ob.snapshot(levels=20)
                if snap.get("bids"):
                    await redis.set(f"ob:snapshot:{sym}", json.dumps(snap), ex=30)
                    published += 1
            except Exception as e:
                log.warning(f"OB snapshot {sym}: {e}")
        if published:
            log.debug(f"OB snapshots published: {published}")
        await asyncio.sleep(2)


async def kline_cache_loop(redis: aioredis.Redis, symbols: list[str]):
    """Cache last 200 1h klines per symbol in Redis every 15 minutes.
    Coin detail page uses this for instant chart loading without external API calls.
    """
    await asyncio.sleep(30)  # wait for WS to settle first
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            start = time.time()
            cached = 0
            for symbol in symbols:
                try:
                    r = await client.get(
                        "https://fapi.binance.com/fapi/v1/klines",
                        params={"symbol": symbol, "interval": "1h", "limit": 200},
                    )
                    if r.status_code == 200:
                        raw = r.json()
                        klines = [
                            {"time": k[0], "open": float(k[1]), "high": float(k[2]),
                             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
                            for k in raw
                        ]
                        await redis.set(f"klines:1h:{symbol}", json.dumps(klines), ex=3600)
                        cached += 1
                    await asyncio.sleep(0.05)  # 50ms between requests — rate limit friendly
                except Exception as e:
                    log.warning(f"Kline cache error {symbol}: {e}")
            elapsed = time.time() - start
            log.info(f"Kline cache: {cached}/{len(symbols)} symbols in {elapsed:.1f}s")
            await asyncio.sleep(max(0, 900 - elapsed))  # target 15-minute refresh


async def main():
    symbols = resolve_symbols()
    log.info(f"data_ingestion starting — {len(symbols)} symbols")

    await init_order_books(symbols)

    # Split into batches for multiple WS connections if > WS_BATCH_SIZE
    batches = [symbols[i:i + WS_BATCH_SIZE] for i in range(0, len(symbols), WS_BATCH_SIZE)]
    ws_tasks = [
        BinanceWebSocketManager(REDIS_URL, batch, on_message=handle_ws_message).connect()
        for batch in batches
    ]
    log.info(f"Starting {len(batches)} WebSocket connection(s) for {len(symbols)} symbols")

    redis = await aioredis.from_url(REDIS_URL)
    await redis.set("ingestion:symbols", json.dumps({"count": len(symbols), "symbols": symbols, "time": time.time()}), ex=600)

    async def _refresh_symbol_manifest():
        while True:
            await redis.set(
                "ingestion:symbols",
                json.dumps({"count": len(symbols), "symbols": symbols, "time": time.time()}),
                ex=600,
            )
            await redis.set("ws:status", json.dumps({
                "status": "CONNECTED",
                "time": time.time(),
                "reconnect_delay": 0,
                "symbols": len(symbols),
            }), ex=45)
            await asyncio.sleep(20)

    signals = CryptoSignalCollector(REDIS_URL, symbols)
    await asyncio.gather(
        *ws_tasks,
        signals.start(),
        ob_snapshot_loop(redis),
        kline_cache_loop(redis, symbols),
    )


if __name__ == "__main__":
    asyncio.run(main())
