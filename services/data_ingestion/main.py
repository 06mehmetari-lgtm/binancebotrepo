import asyncio
import logging
import os

from binance_ws import BinanceWebSocketManager
from order_book import LocalOrderBook
from crypto_signals import CryptoSignalCollector
from symbol_discovery import fetch_top_symbols

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOLS_RAW = os.getenv("SYMBOLS", "AUTO")
TOP_N = int(os.getenv("TOP_SYMBOLS", "100"))
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

    signals = CryptoSignalCollector(REDIS_URL, symbols)
    await asyncio.gather(*ws_tasks, signals.start())


if __name__ == "__main__":
    asyncio.run(main())
