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
from cvd_features import CVDFeatureBuilder
from volume_profile import VolumeProfileBuilder
from mtf_features import MTFFeatureBuilder
from drift_detector import DriftDetector
from ml_signal import MLSignalPredictor
from online_learner import OnlineLearner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOLS_RAW = os.getenv("SYMBOLS", "AUTO")
TOP_N = int(os.getenv("TOP_SYMBOLS", "500"))

SYMBOL_REFRESH_INTERVAL = 300

price_builder   = PriceFeatureBuilder()
ob_builder      = OrderBookFeatureBuilder()
crypto_builder  = CryptoFeatureBuilder()
cvd_builder     = CVDFeatureBuilder()
vp_builder      = VolumeProfileBuilder()
mtf_builder     = MTFFeatureBuilder()
drift_detectors: dict[str, DriftDetector] = {}
ml_predictor    = MLSignalPredictor()
online_learner  = OnlineLearner(ml_predictor)

OHLCV_HISTORY: dict[str, list] = {}


def _resolve_symbols_from_env() -> list[str]:
    """Called only as a last resort when Redis has no data yet."""
    if SYMBOLS_RAW.strip().upper() != "AUTO":
        return [s.strip() for s in SYMBOLS_RAW.split(",") if s.strip()]
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        with urllib.request.urlopen(url, timeout=15) as r:
            tickers = json.loads(r.read())
        ranked = sorted(
            [t for t in tickers if t["symbol"].endswith("USDT")],
            key=lambda x: float(x.get("quoteVolume", 0)), reverse=True
        )
        syms = [t["symbol"] for t in ranked[:TOP_N]]
        log.info(f"Binance REST discovery: {len(syms)} symbols")
        return syms
    except Exception as e:
        log.warning(f"Binance REST discovery failed: {e} — using extended fallback list")
        return [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
            "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
            "MATICUSDT", "UNIUSDT", "ATOMUSDT", "LTCUSDT", "NEARUSDT",
            "FILUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "SUIUSDT",
        ]


async def discover_symbols_from_redis(redis: aioredis.Redis) -> list[str]:
    """Discover all symbols that data_ingestion is actively streaming into Redis."""
    def _decode(key: bytes | str) -> str:
        return key.decode() if isinstance(key, bytes) else key

    # data_ingestion writes binance:kline:{symbol.lower()} for every subscribed symbol
    kline_keys = await redis.keys("binance:kline:*")
    if kline_keys:
        symbols = sorted(_decode(k).replace("binance:kline:", "").upper() for k in kline_keys)
        log.info(f"Redis symbol discovery: {len(symbols)} symbols from binance:kline:* keys")
        return symbols

    # Fallback: orderbook keys (written by data_ingestion for all depth stream symbols)
    ob_keys = await redis.keys("binance:ob:*")
    if ob_keys:
        symbols = sorted(_decode(k).replace("binance:ob:", "").upper() for k in ob_keys)
        log.info(f"Redis symbol discovery (OB): {len(symbols)} symbols from binance:ob:* keys")
        return symbols

    return []


def _fetch_klines_sync(symbol: str, limit: int = 300) -> list:
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1m&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        return [[float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in data]
    except Exception as e:
        log.warning(f"Bootstrap klines failed for {symbol}: {e}")
        return []


async def bootstrap_klines(symbols: list[str]):
    loop = asyncio.get_event_loop()
    for symbol in symbols:
        if len(OHLCV_HISTORY.get(symbol, [])) >= 30:
            continue  # already bootstrapped
        candles = await loop.run_in_executor(None, _fetch_klines_sync, symbol)
        if candles:
            OHLCV_HISTORY[symbol] = candles
            log.info(f"Bootstrap: {symbol} loaded {len(candles)} klines")
        else:
            OHLCV_HISTORY.setdefault(symbol, [])


async def compute_features(redis: aioredis.Redis, symbol: str) -> dict | None:
    try:
        sym_lo = symbol.lower()
        pipeline = redis.pipeline()
        pipeline.lindex(f"binance:ob:{sym_lo}", 0)        # 0
        pipeline.lrange(f"binance:trade:{sym_lo}", 0, 499) # 1 — last 500 trades for CVD
        pipeline.lrange(f"liq:recent:{symbol}", 0, 199)   # 2 — liquidations
        pipeline.get(f"funding:{symbol}")                  # 3
        pipeline.get(f"oi:{symbol}")                       # 4
        pipeline.get(f"ls_ratio:{symbol}")                 # 5
        pipeline.get("sentiment:fear_greed")               # 6
        pipeline.get(f"sentiment:reddit:{symbol}")         # 7
        pipeline.get("macro:vix")                          # 8
        pipeline.get(f"klines:1h:{symbol}")                # 9
        res = await pipeline.execute()

        ob_raw      = res[0]
        trades_raw  = res[1] or []
        liq_raw     = res[2] or []
        funding_raw = res[3]
        oi_raw      = res[4]
        ls_raw      = res[5]
        fg_raw      = res[6]
        reddit_raw  = res[7]
        vix_raw     = res[8]
        klines_1h   = res[9]

        ob_snapshot = json.loads(ob_raw)["data"] if ob_raw else {}

        crypto: dict = {}
        if funding_raw: crypto.update(json.loads(funding_raw))
        if oi_raw:      crypto.update(json.loads(oi_raw))
        if ls_raw:      crypto.update(json.loads(ls_raw))
        if fg_raw:      crypto["fear_greed"]      = json.loads(fg_raw).get("value", 50)
        if reddit_raw:  crypto["reddit_sentiment"] = json.loads(reddit_raw).get("score", 0)
        if vix_raw:     crypto["vix_level"]        = json.loads(vix_raw).get("value", 20)

        history = OHLCV_HISTORY.get(symbol, [])
        if len(history) < 30:
            return None

        df = pd.DataFrame(history[-200:], columns=["open", "high", "low", "close", "volume"])
        price_feats = price_builder.build(df)
        if price_feats.empty:
            return None
        last_row = price_feats.iloc[-1].to_dict()

        ob_feats     = ob_builder.build(ob_snapshot)
        crypto_feats = crypto_builder.build(crypto)
        cvd_feats    = cvd_builder.build(trades_raw, liq_raw)
        vp_feats     = vp_builder.build(history)
        mtf_feats    = mtf_builder.build(klines_1h, last_row)

        features: dict = {}
        for k, v in last_row.items():
            features[k] = float(v) if v == v else 0.0
        features.update(ob_feats)
        features.update(crypto_feats)
        features.update(cvd_feats)
        features.update(vp_feats)
        features.update(mtf_feats)
        features["symbol"]    = symbol
        features["timestamp"] = time.time()

        if symbol not in drift_detectors:
            drift_detectors[symbol] = DriftDetector()
        rsi   = features.get("rsi_14", 50) / 100
        drift = drift_detectors[symbol].update(rsi)
        features["drift_status"] = "DRIFTING" if drift else "STABLE"

        # ML signal score — heuristic until first retrain, then learned model
        features["ml_score"] = round(ml_predictor.predict(features), 4)

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
    if kline and kline.get("x"):  # closed kline only
        candle = [
            float(kline["o"]), float(kline["h"]),
            float(kline["l"]), float(kline["c"]),
            float(kline["v"])
        ]
        history = OHLCV_HISTORY.setdefault(symbol, [])
        history.append(candle)
        if len(history) > 500:
            OHLCV_HISTORY[symbol] = history[-500:]


async def _model_refresh_loop(redis: aioredis.Redis):
    """Reload ML model from Redis every 10 minutes (in case online_learner updated it)."""
    while True:
        await asyncio.sleep(600)
        try:
            model_bytes = await redis.get("ml:model:v2")
            if model_bytes:
                from online_learner import MODEL_VERSION_KEY
                version_raw = await redis.get(MODEL_VERSION_KEY)
                version = int(version_raw) if version_raw else 0
                if version > ml_predictor._model_version:
                    ml_predictor.load_bytes(model_bytes, version)
                    log.info(f"ML model refreshed to version {version}")
        except Exception as e:
            log.warning(f"ML model refresh error: {e}")


async def main():
    redis = await aioredis.from_url(REDIS_URL)
    redis_learner = await aioredis.from_url(REDIS_URL)

    # Wait for data_ingestion to populate Redis keys (retry up to 2 minutes)
    active_symbols: list[str] = []
    for attempt in range(12):
        active_symbols = await discover_symbols_from_redis(redis)
        if active_symbols:
            break
        log.info(f"Waiting for data_ingestion keys in Redis (attempt {attempt + 1}/12)...")
        await asyncio.sleep(10)

    if not active_symbols:
        log.warning("No symbols found in Redis — falling back to env/REST discovery")
        active_symbols = _resolve_symbols_from_env()

    log.info(f"feature_engine starting — {len(active_symbols)} symbols")

    log.info("Bootstrapping klines from Binance REST API...")
    await bootstrap_klines(active_symbols)

    active_set: set[str] = set(active_symbols)
    last_refresh = time.time()

    BATCH = 50
    FEAT_TTL = 300

    async def _process(symbol: str):
        try:
            await update_ohlcv(redis, symbol)
            features = await compute_features(redis, symbol)
            if features:
                await redis.set(f"features:latest:{symbol}", json.dumps(features), ex=FEAT_TTL)
                await redis.publish(f"ch:features:{symbol}", symbol)
                await redis.set(
                    f"ml:signal_features:{symbol}",
                    json.dumps(ml_predictor.extract_vector(features)),
                    ex=FEAT_TTL * 4,
                )
        except Exception as e:
            log.error(f"Feature error [{symbol}]: {e}")

    async def feature_loop():
        nonlocal active_set, last_refresh
        while True:
            if time.time() - last_refresh > SYMBOL_REFRESH_INTERVAL:
                new_symbols = await discover_symbols_from_redis(redis)
                if new_symbols:
                    added = set(new_symbols) - active_set
                    if added:
                        log.info(f"New symbols discovered: {len(added)}")
                        await bootstrap_klines(list(added))
                    active_set = set(new_symbols)
                last_refresh = time.time()

            symbols_list = list(active_set)
            for i in range(0, len(symbols_list), BATCH):
                await asyncio.gather(*[_process(s) for s in symbols_list[i:i + BATCH]])

            await asyncio.sleep(1)

    await asyncio.gather(
        feature_loop(),
        online_learner.run(redis_learner),
        _model_refresh_loop(redis),
    )


if __name__ == "__main__":
    asyncio.run(main())
