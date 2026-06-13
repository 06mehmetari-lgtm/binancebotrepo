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
from timescale_writer import schedule_write

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOLS_RAW = os.getenv("SYMBOLS", "AUTO")
TOP_N = int(os.getenv("TOP_SYMBOLS", "500"))

# Symbol refresh interval — re-scan Redis every 5 minutes to pick up new symbols
SYMBOL_REFRESH_INTERVAL = 300

price_builder = PriceFeatureBuilder()
ob_builder = OrderBookFeatureBuilder()
crypto_builder = CryptoFeatureBuilder()
drift_detectors: dict[str, DriftDetector] = {}

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


async def bootstrap_klines(symbols: list[str], redis: aioredis.Redis | None = None):
    loop = asyncio.get_event_loop()
    for i, symbol in enumerate(symbols):
        if len(OHLCV_HISTORY.get(symbol, [])) >= 30:
            continue
        candles = await loop.run_in_executor(None, _fetch_klines_sync, symbol)
        if candles:
            OHLCV_HISTORY[symbol] = candles
            log.info(f"Bootstrap: {symbol} loaded {len(candles)} klines")
        else:
            OHLCV_HISTORY.setdefault(symbol, [])
        if redis and i % 15 == 14:
            await heartbeat(redis)


async def compute_features(redis: aioredis.Redis, symbol: str) -> dict | None:
    try:
        ob_snapshot: dict = {}
        snap_raw = await redis.get(f"ob:snapshot:{symbol}")
        if snap_raw:
            ob_snapshot = json.loads(snap_raw)
        else:
            ob_raw = await redis.lindex(f"binance:ob:{symbol.lower()}", 0)
            if ob_raw:
                ob_snapshot = json.loads(ob_raw).get("data", json.loads(ob_raw))

        funding_raw = await redis.get(f"funding:{symbol}")
        oi_raw = await redis.get(f"oi:{symbol}")
        ls_raw = await redis.get(f"ls_ratio:{symbol}")
        fg_raw = await redis.get("sentiment:fear_greed")
        reddit_raw = await redis.get(f"sentiment:reddit:{symbol}")
        vix_raw = await redis.get("macro:vix")

        crypto: dict = {}
        if funding_raw: crypto.update(json.loads(funding_raw))
        if oi_raw: crypto.update(json.loads(oi_raw))
        if ls_raw: crypto.update(json.loads(ls_raw))
        if fg_raw:
            fg = json.loads(fg_raw)
            crypto["fear_greed"] = fg.get("value", 50)
        if reddit_raw: crypto["reddit_sentiment"] = json.loads(reddit_raw).get("score", 0)
        if vix_raw: crypto["vix_level"] = json.loads(vix_raw).get("value", 20)

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

        features: dict = {}
        for k, v in last_row.items():
            features[k] = float(v) if v == v else 0.0  # NaN → 0
        features.update(ob_feats)
        features.update(crypto_feats)
        features["symbol"] = symbol
        features["timestamp"] = time.time()
        if history:
            features["close"] = float(history[-1][3])
            features["last_price"] = features["close"]

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


async def heartbeat(redis: aioredis.Redis) -> None:
    """Dashboard /system checks this key; must refresh more often than 90s cycle time."""
    await redis.set("system:heartbeat:feature_engine", str(time.time()), ex=120)


async def main():
    redis = await aioredis.from_url(REDIS_URL)
    await heartbeat(redis)

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
    await bootstrap_klines(active_symbols, redis)
    await heartbeat(redis)

    active_set: set[str] = set(active_symbols)
    last_refresh = time.time()

    BATCH = 50  # concurrent symbols per gather call
    FEAT_TTL = 300  # seconds — longer TTL to handle large symbol sets

    async def _process(symbol: str):
        try:
            await update_ohlcv(redis, symbol)
            features = await compute_features(redis, symbol)
            if features:
                await redis.set(f"features:latest:{symbol}", json.dumps(features), ex=FEAT_TTL)
                await redis.publish(f"ch:features:{symbol}", symbol)
                schedule_write(symbol, features)
        except Exception as e:
            log.error(f"Feature error [{symbol}]: {e}")

    while True:
        await heartbeat(redis)
        if time.time() - last_refresh > SYMBOL_REFRESH_INTERVAL:
            new_symbols = await discover_symbols_from_redis(redis)
            if new_symbols:
                added = set(new_symbols) - active_set
                if added:
                    log.info(f"New symbols discovered: {len(added)}")
                    await bootstrap_klines(list(added), redis)
                active_set = set(new_symbols)
            last_refresh = time.time()

        symbols_list = list(active_set)
        for i in range(0, len(symbols_list), BATCH):
            await asyncio.gather(*[_process(s) for s in symbols_list[i:i + BATCH]])
            await heartbeat(redis)

        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
