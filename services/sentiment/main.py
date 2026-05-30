import asyncio
import logging

from reddit_scraper import RedditScraper
from cryptopanic import CryptoPanicFeed
from fear_greed import FearGreedIndex
from finbert_analyzer import FinBERTAnalyzer

logging.basicConfig(level="INFO", format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


async def main():
    log.info("sentiment service starting")
    await asyncio.gather(
        RedditScraper().run(),
        CryptoPanicFeed().run(),
        FearGreedIndex().run(),
        FinBERTAnalyzer().run(),
    )


if __name__ == "__main__":
    asyncio.run(main())
