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
SYMBOL_REFRESH_INTERVAL = 300

regime_classifier = RegimeClassifier()
crisis_detector = CrisisDetector()

FEATURE_HISTORY: dict[str, list] = {}
LAST_REGIME: dict[str, str] = {}
_tick_count = 0


async def discover_symbols(redis: aioredis.Redis) -> list[str]:
    keys = await redis.keys("features:latest:*")
    symbols = [
        (k.decode() if isinstance(k, bytes) else k).split(":")[-1]
        for k in keys
    ]
    return sorted(symbols) if symbols else ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


def _refit_classifier():
    """Refit regime classifier using recent history from all tracked symbols."""
    all_vecs = []
    for history in FEATURE_HISTORY.values():
        all_vecs.extend(history[-100:])
    if len(all_vecs) >= 100:
        regime_classifier.fit(np.array(all_vecs))
        log.info(f"Regime classifier refitted with {len(all_vecs)} samples from {len(FEATURE_HISTORY)} symbols")


async def compute_context(redis: aioredis.Redis, symbol: str) -> dict | None:
    feat_raw = await redis.get(f"features:latest:{symbol}")
    if not feat_raw:
        return None
    features = json.loads(feat_raw)

    numeric_keys = ["rsi_14", "macd_hist", "imbalance_5", "funding_rate",
                    "oi_change_1h", "ls_ratio_z", "fear_greed_norm", "vix_level"]
    vec = [float(features.get(k, 0) or 0) for k in numeric_keys]
    history = FEATURE_HISTORY.setdefault(symbol, [])
    history.append(vec)
    if len(history) > 500:
        FEATURE_HISTORY[symbol] = history[-500:]

    # Regime classification
    regime = "unknown"
    if len(history) >= 50 and regime_classifier.fitted:
        try:
            regime = regime_classifier.predict(np.array([vec]))
        except Exception:
            pass
    elif len(history) >= 50 and not regime_classifier.fitted:
        _refit_classifier()
        try:
            regime = regime_classifier.predict(np.array([vec]))
        except Exception:
            pass

    # Crisis detection — use mom_5 as proxy for BTC 1h return when no dedicated field
    vix_raw = float(features.get("vix_level", 0) or 0)
    metrics = {
        "vix": vix_raw * 100,
        "btc_return_1h": float(features.get("mom_5", 0) or 0) / 100,
        "funding_rate": float(features.get("funding_rate", 0) or 0),
        "liquidation_volume": 0,
    }
    liq_raw = await redis.lindex("liquidations:large", 0)
    if liq_raw:
        try:
            liq = json.loads(liq_raw)
            metrics["liquidation_volume"] = float(liq.get("value_usdt", 0))
        except Exception:
            pass

    crisis_triggers = crisis_detector.detect(metrics)
    crisis_level = min(len(crisis_triggers), 4)

    context = {
        "symbol": symbol,
        "regime": regime,
        "crisis_level": crisis_level,
        "crisis_triggers": crisis_triggers,
        "drift_status": features.get("drift_status", "STABLE"),
        "fear_greed": float(features.get("fear_greed_norm", 0.5) or 0.5) * 100,
        "funding_rate": float(features.get("funding_rate", 0) or 0),
        "ls_ratio": float(features.get("ls_ratio_z", 0) or 0),
        "vix_level": vix_raw * 100,
        "reddit_sentiment": float(features.get("reddit_sentiment", 0) or 0),
        "onchain_netflow": float(features.get("onchain_netflow", 0) or 0),
        "timestamp": time.time(),
    }
    return context


async def main():
    global _tick_count
    log.info("context_engine starting — discovering symbols dynamically")
    redis = await aioredis.from_url(REDIS_URL)

    symbols: list[str] = []
    last_refresh = 0.0
    BATCH = 50
    CTX_TTL = 300

    async def _process(symbol: str):
        global _tick_count
        try:
            ctx = await compute_context(redis, symbol)
            if not ctx:
                return
            await redis.set(f"context:latest:{symbol}", json.dumps(ctx), ex=CTX_TTL)
            await redis.publish(f"ch:context:{symbol}", symbol)
            # Keep a global regime key (BTC drives the market regime)
            if symbol in ("BTCUSDT", "ETHUSDT"):
                await redis.set("context:regime", ctx["regime"], ex=CTX_TTL)
                await redis.set("context:crisis_level", str(ctx["crisis_level"]), ex=CTX_TTL)

            new_regime = ctx.get("regime", "unknown")
            old_regime = LAST_REGIME.get(symbol)
            if old_regime and old_regime != new_regime and new_regime != "unknown":
                LAST_REGIME[symbol] = new_regime
                await redis.lpush("activity:feed", json.dumps({
                    "type": "regime_change",
                    "time": time.time(),
                    "symbol": symbol,
                    "regime": new_regime,
                    "prev_regime": old_regime,
                    "crisis_level": ctx.get("crisis_level", 0),
                }))
                await redis.ltrim("activity:feed", 0, 499)
            elif not old_regime:
                LAST_REGIME[symbol] = new_regime

            _tick_count += 1
            # Refit regime classifier every 2000 ticks using all accumulated data
            if _tick_count % 2000 == 0:
                _refit_classifier()

        except Exception as e:
            log.error(f"Context error [{symbol}]: {e}")

    while True:
        now = time.time()
        if now - last_refresh > SYMBOL_REFRESH_INTERVAL or not symbols:
            symbols = await discover_symbols(redis)
            last_refresh = now
            log.info(f"context_engine tracking {len(symbols)} symbols")

        for i in range(0, len(symbols), BATCH):
            await asyncio.gather(*[_process(s) for s in symbols[i:i + BATCH]])
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
