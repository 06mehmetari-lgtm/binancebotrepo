import asyncio, logging
from reddit_scraper import RedditScraper
from cryptopanic import CryptoPanicFeed
from fear_greed import FearGreedIndex

logging.basicConfig(level="INFO")
log = logging.getLogger(__name__)

async def main():
    log.info("sentiment service starting")
    await asyncio.gather(
        RedditScraper().run(),
        CryptoPanicFeed().run(),
        FearGreedIndex().run(),
    )

if __name__ == "__main__":
    asyncio.run(main())
