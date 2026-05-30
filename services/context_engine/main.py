import asyncio
import json
import logging
import os
import time

import numpy as np
import redis.asyncio as aioredis

from regime_classifier import RegimeClassifier
from crisis_detector import CrisisDetector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOLS_RAW = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
SYMBOLS = [s.strip() for s in SYMBOLS_RAW.split(",") if s.strip()]

regime_classifier = RegimeClassifier()
crisis_detector = CrisisDetector()

FEATURE_HISTORY: dict[str, list] = {s: [] for s in SYMBOLS}


async def compute_context(redis: aioredis.Redis, symbol: str) -> dict | None:
    feat_raw = await redis.get(f"features:latest:{symbol}")
    if not feat_raw:
        return None
    features = json.loads(feat_raw)

    # Track feature history for regime classifier
    numeric_keys = ["rsi_14", "macd_hist", "imbalance_5", "funding_rate",
                    "oi_change_1h", "ls_ratio_z", "fear_greed_norm", "vix_level"]
    vec = [float(features.get(k, 0)) for k in numeric_keys]
    history = FEATURE_HISTORY.setdefault(symbol, [])
    history.append(vec)
    if len(history) > 500:
        FEATURE_HISTORY[symbol] = history[-500:]

    # Regime classification (needs 50+ samples to fit)
    regime = "unknown"
    if len(history) >= 50:
        arr = np.array(history)
        if not regime_classifier.fitted:
            regime_classifier.fit(arr)
        regime = regime_classifier.predict(np.array([vec]))

    # Crisis detection
    metrics = {
        "vix": float(features.get("vix_level", 0)) * 100,
        "btc_return_1h": float(features.get("mom_5", 0)) / 100,
        "funding_rate": float(features.get("funding_rate", 0)) / 1000,
        "liquidation_volume": 0,
    }
    liq_raw = await redis.lindex("liquidations:large", 0)
    if liq_raw:
        liq = json.loads(liq_raw)
        metrics["liquidation_volume"] = float(liq.get("value_usdt", 0))

    crisis_triggers = crisis_detector.detect(metrics)
    crisis_level = min(len(crisis_triggers), 4)

    context = {
        "symbol": symbol,
        "regime": regime,
        "crisis_level": crisis_level,
        "crisis_triggers": crisis_triggers,
        "drift_status": features.get("drift_status", "STABLE"),
        "fear_greed": float(features.get("fear_greed_norm", 0.5)) * 100,
        "funding_rate": float(features.get("funding_rate", 0)) / 1000,
        "ls_ratio": float(features.get("ls_ratio_z", 0)),
        "vix_level": float(features.get("vix_level", 0)) * 100,
        "reddit_sentiment": float(features.get("reddit_sentiment", 0)),
        "onchain_netflow": float(features.get("onchain_netflow", 0)),
        "timestamp": time.time(),
    }
    return context


async def main():
    log.info(f"context_engine starting — symbols: {SYMBOLS}")
    redis = await aioredis.from_url(REDIS_URL)

    while True:
        for symbol in SYMBOLS:
            ctx = await compute_context(redis, symbol)
            if ctx:
                await redis.set(f"context:latest:{symbol}", json.dumps(ctx), ex=120)
                await redis.publish(f"ch:context:{symbol}", symbol)
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
