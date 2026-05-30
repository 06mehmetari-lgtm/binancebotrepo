import asyncio, logging
from price_features import PriceFeatureBuilder
from orderbook_features import OrderBookFeatureBuilder
from crypto_features import CryptoFeatureBuilder
from drift_detector import DriftDetector
from feature_selector import FeatureSelector

logging.basicConfig(level="INFO")

async def main():
    logging.info("feature_engine starting")
    await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
