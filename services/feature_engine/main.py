import asyncio
import json
import logging
import os
import time
import urllib.request

import pandas as pd
import redis.asyncio as aioredis

from price_features import PriceFeatureBuilder
from orderbook_features import OrderBookFeatureBuilder
from crypto_features import CryptoFeatureBuilder
from drift_detector import DriftDetector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOLS_RAW = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
SYMBOLS = [s.strip() for s in SYMBOLS_RAW.split(",") if s.strip()]

price_builder = PriceFeatureBuilder()
ob_builder = OrderBookFeatureBuilder()
crypto_builder = CryptoFeatureBuilder()
drift_detectors: dict[str, DriftDetector] = {}

OHLCV_HISTORY: dict[str, list] = {s: [] for s in SYMBOLS}


def _fetch_klines_sync(symbol: str, limit: int = 300) -> list:
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1m&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        return [[float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in data]
    except Exception as e:
        log.warning(f"Bootstrap klines failed for {symbol}: {e}")
        return []


async def bootstrap_klines():
    loop = asyncio.get_event_loop()
    for symbol in SYMBOLS:
        candles = await loop.run_in_executor(None, _fetch_klines_sync, symbol)
        if candles:
            OHLCV_HISTORY[symbol] = candles
            log.info(f"Bootstrap: {symbol} loaded {len(candles)} klines from Binance REST")
        else:
            log.warning(f"Bootstrap: no klines for {symbol}, will rely on WebSocket")


async def compute_features(redis: aioredis.Redis, symbol: str) -> dict | None:
    try:
        # Order book snapshot (latest from list)
        ob_raw = await redis.lindex(f"binance:ob:{symbol.lower()}", 0)
        ob_snapshot = json.loads(ob_raw)["data"] if ob_raw else {}

        # Crypto context
        funding_raw = await redis.get(f"funding:{symbol}")
        oi_raw = await redis.get(f"oi:{symbol}")
        ls_raw = await redis.get(f"ls_ratio:{symbol}")
        fg_raw = await redis.get("sentiment:fear_greed")
        reddit_raw = await redis.get(f"sentiment:reddit:{symbol}")
        vix_raw = await redis.get("macro:vix")

        crypto = {}
        if funding_raw: crypto.update(json.loads(funding_raw))
        if oi_raw: crypto.update(json.loads(oi_raw))
        if ls_raw: crypto.update(json.loads(ls_raw))
        if fg_raw:
            fg = json.loads(fg_raw)
            crypto["fear_greed"] = fg.get("value", 50)
        if reddit_raw: crypto["reddit_sentiment"] = json.loads(reddit_raw).get("score", 0)
        if vix_raw: crypto["vix_level"] = json.loads(vix_raw).get("value", 20)

        # Price features from historical klines in memory
        history = OHLCV_HISTORY.get(symbol, [])
        if len(history) < 30:
            return None

        df = pd.DataFrame(history[-200:], columns=["open", "high", "low", "close", "volume"])
        price_feats = price_builder.build(df)
        if price_feats.empty:
            return None
        last_row = price_feats.iloc[-1].to_dict()

        ob_feats = ob_builder.build(ob_snapshot)
        crypto_feats = crypto_builder.build(crypto)

        features = {}
        for k, v in last_row.items():
            features[k] = float(v) if v == v else 0.0  # NaN → 0
        features.update(ob_feats)
        features.update(crypto_feats)
        features["symbol"] = symbol
        features["timestamp"] = time.time()

        # Drift detection
        if symbol not in drift_detectors:
            drift_detectors[symbol] = DriftDetector()
        rsi = features.get("rsi_14", 50) / 100
        drift = drift_detectors[symbol].update(rsi)
        features["drift_status"] = "DRIFTING" if drift else "STABLE"

        return features

    except Exception as e:
        log.error(f"Feature computation error for {symbol}: {e}")
        return None


async def update_ohlcv(redis: aioredis.Redis, symbol: str):
    kline_raw = await redis.lindex(f"binance:kline:{symbol.lower()}", 0)
    if not kline_raw:
        return
    data = json.loads(kline_raw)
    kline = data.get("data", {}).get("k", {})
    if kline and kline.get("x"):  # closed kline
        candle = [
            float(kline["o"]), float(kline["h"]),
            float(kline["l"]), float(kline["c"]),
            float(kline["v"])
        ]
        history = OHLCV_HISTORY.setdefault(symbol, [])
        history.append(candle)
        if len(history) > 500:
            OHLCV_HISTORY[symbol] = history[-500:]


async def main():
    log.info(f"feature_engine starting — symbols: {SYMBOLS}")
    redis = await aioredis.from_url(REDIS_URL)

    log.info("Bootstrapping klines from Binance REST API...")
    await bootstrap_klines()

    while True:
        for symbol in SYMBOLS:
            await update_ohlcv(redis, symbol)
            features = await compute_features(redis, symbol)
            if features:
                await redis.set(
                    f"features:latest:{symbol}",
                    json.dumps(features),
                    ex=120
                )
                await redis.publish(f"ch:features:{symbol}", symbol)
                log.info(f"Features computed: {symbol} rsi={features.get('rsi_14', 0):.1f} drift={features.get('drift_status')}")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())


async def compute_features(redis: aioredis.Redis, symbol: str) -> dict | None:
    try:
        # Order book snapshot (latest from list)
        ob_raw = await redis.lindex(f"binance:ob:{symbol.lower()}", 0)
        ob_snapshot = json.loads(ob_raw)["data"] if ob_raw else {}

        # Crypto context
        funding_raw = await redis.get(f"funding:{symbol}")
        oi_raw = await redis.get(f"oi:{symbol}")
        ls_raw = await redis.get(f"ls_ratio:{symbol}")
        fg_raw = await redis.get("sentiment:fear_greed")
        reddit_raw = await redis.get(f"sentiment:reddit:{symbol}")
        vix_raw = await redis.get("macro:vix")

        crypto = {}
        if funding_raw: crypto.update(json.loads(funding_raw))
        if oi_raw: crypto.update(json.loads(oi_raw))
        if ls_raw: crypto.update(json.loads(ls_raw))
        if fg_raw:
            fg = json.loads(fg_raw)
            crypto["fear_greed"] = fg.get("value", 50)
        if reddit_raw: crypto["reddit_sentiment"] = json.loads(reddit_raw).get("score", 0)
        if vix_raw: crypto["vix_level"] = json.loads(vix_raw).get("value", 20)

        # Price features from historical klines in memory
        history = OHLCV_HISTORY.get(symbol, [])
        if len(history) < 30:
            return None

        df = pd.DataFrame(history[-200:], columns=["open", "high", "low", "close", "volume"])
        price_feats = price_builder.build(df)
        if price_feats.empty:
            return None
        last_row = price_feats.iloc[-1].to_dict()

        ob_feats = ob_builder.build(ob_snapshot)
        crypto_feats = crypto_builder.build(crypto)

        features = {}
        for k, v in last_row.items():
            features[k] = float(v) if v == v else 0.0  # NaN → 0
        features.update(ob_feats)
        features.update(crypto_feats)
        features["symbol"] = symbol
        features["timestamp"] = time.time()

        # Drift detection
        if symbol not in drift_detectors:
            drift_detectors[symbol] = DriftDetector()
        rsi = features.get("rsi_14", 50) / 100
        drift = drift_detectors[symbol].update(rsi)
        features["drift_status"] = "DRIFTING" if drift else "STABLE"

        return features

    except Exception as e:
        log.error(f"Feature computation error for {symbol}: {e}")
        return None


async def update_ohlcv(redis: aioredis.Redis, symbol: str):
    kline_raw = await redis.lindex(f"binance:kline:{symbol.lower()}", 0)
    if not kline_raw:
        return
    data = json.loads(kline_raw)
    kline = data.get("data", {}).get("k", {})
    if kline and kline.get("x"):  # closed kline
        candle = [
            float(kline["o"]), float(kline["h"]),
            float(kline["l"]), float(kline["c"]),
            float(kline["v"])
        ]
        history = OHLCV_HISTORY.setdefault(symbol, [])
        history.append(candle)
        if len(history) > 500:
            OHLCV_HISTORY[symbol] = history[-500:]


async def main():
    log.info(f"feature_engine starting — symbols: {SYMBOLS}")
    redis = await aioredis.from_url(REDIS_URL)

    while True:
        for symbol in SYMBOLS:
            await update_ohlcv(redis, symbol)
            features = await compute_features(redis, symbol)
            if features:
                await redis.set(
                    f"features:latest:{symbol}",
                    json.dumps(features),
                    ex=120
                )
                await redis.publish(f"ch:features:{symbol}", symbol)
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
