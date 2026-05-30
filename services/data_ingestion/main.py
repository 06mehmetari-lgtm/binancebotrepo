import asyncio
import logging
import os

from binance_ws import BinanceWebSocketManager
from order_book import LocalOrderBook
from crypto_signals import CryptoSignalCollector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOLS_RAW = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
SYMBOLS = [s.strip() for s in SYMBOLS_RAW.split(",") if s.strip()]

order_books: dict[str, LocalOrderBook] = {}


async def handle_ws_message(stream: str, payload: dict, quality: int):
    symbol = payload.get("s", "").upper()
    event_type = payload.get("e", "")
    if event_type == "depthUpdate" and symbol in order_books:
        order_books[symbol].process_event(payload)


async def init_order_books():
    for symbol in SYMBOLS:
        ob = LocalOrderBook(symbol)
        await ob.initialize()
        order_books[symbol] = ob
    log.info(f"Order books initialized: {list(order_books.keys())}")


async def main():
    log.info(f"data_ingestion starting — symbols: {SYMBOLS}")
    await init_order_books()
    ws = BinanceWebSocketManager(REDIS_URL, SYMBOLS, on_message=handle_ws_message)
    signals = CryptoSignalCollector(REDIS_URL, SYMBOLS)
    await asyncio.gather(ws.connect(), signals.start())


if __name__ == "__main__":
    asyncio.run(main())
