import asyncio
import logging
from binance_ws import BinanceWebSocket

logging.basicConfig(level="INFO")
log = logging.getLogger(__name__)

async def main():
    log.info("data_ingestion service starting")
    ws = BinanceWebSocket()
    await ws.run()

if __name__ == "__main__":
    asyncio.run(main())
