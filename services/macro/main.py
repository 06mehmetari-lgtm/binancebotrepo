import asyncio, logging
from fred_api import FredFeed
from yfinance_feed import YFinanceFeed
from onchain import OnChainFeed

logging.basicConfig(level="INFO")

async def main():
    await asyncio.gather(
        FredFeed().run(),
        YFinanceFeed().run(),
        OnChainFeed().run(),
    )

if __name__ == "__main__":
    asyncio.run(main())
