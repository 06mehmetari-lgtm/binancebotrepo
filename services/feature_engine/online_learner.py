"""
Online Learner — Phase 3.
Consumes labeled trade outcomes from Redis, retrains the ML model
every RETRAIN_EVERY samples using walk-forward validation.
Runs as a background task inside feature_engine.
"""
import asyncio
import json
import logging
import time

import redis.asyncio as aioredis

from ml_signal import MLSignalPredictor, FEATURE_KEYS, MODEL_REDIS_KEY

log = logging.getLogger(__name__)

TRAINING_DATA_KEY = "ml:training_data"  # Redis list of JSON samples
TRAINING_DATA_MAX = 2000                # keep last N samples
RETRAIN_EVERY     = 50                  # retrain when N new samples accumulated
MIN_SAMPLES       = 60                  # don't train with fewer than this
STATS_KEY         = "ml:learner:stats"
MODEL_VERSION_KEY = "ml:model:version"


class OnlineLearner:
    def __init__(self, predictor: MLSignalPredictor):
        self._predictor = predictor
        self._samples_since_retrain = 0

    async def run(self, redis: aioredis.Redis):
        """Background loop: subscribe to trade outcomes and retrain periodically."""
        log.info("OnlineLearner started — subscribing to ch:trade_closed")

        # Load existing model from Redis on startup
        await self._load_model(redis)

        pubsub = redis.pubsub()
        await pubsub.subscribe("ch:trade_closed")

        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            try:
                await self._handle_trade(redis, msg["data"])
            except Exception as e:
                log.error(f"OnlineLearner trade handler error: {e}")

    async def _handle_trade(self, redis: aioredis.Redis, raw):
        trade = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        symbol   = trade.get("symbol", "")
        pnl_pct  = float(trade.get("pnl_pct", 0))
        direction = trade.get("direction", "flat")

        if not symbol or direction == "flat":
            return

        # Fetch feature vector stored at signal time
        feat_raw = await redis.get(f"ml:signal_features:{symbol}")
        if not feat_raw:
            return
        feature_vec = json.loads(feat_raw)

        # Label: +1 = this direction was profitable, -1 = was not
        # 0 = flat (shouldn't appear since we filtered above)
        if direction == "long":
            label = 1 if pnl_pct > 0 else 0
        elif direction == "short":
            label = 2 if pnl_pct > 0 else 0
        else:
            return

        sample = {
            "features": feature_vec,
            "label": label,
            "symbol": symbol,
            "pnl_pct": pnl_pct,
            "direction": direction,
            "ts": time.time(),
        }
        await redis.lpush(TRAINING_DATA_KEY, json.dumps(sample))
        await redis.ltrim(TRAINING_DATA_KEY, 0, TRAINING_DATA_MAX - 1)

        self._samples_since_retrain += 1
        log.debug(f"OnlineLearner: {symbol} {direction} label={label} pnl={pnl_pct:.2%}")

        if self._samples_since_retrain >= RETRAIN_EVERY:
            self._samples_since_retrain = 0
            await self._retrain(redis)

    async def _retrain(self, redis: aioredis.Redis):
        raw_samples = await redis.lrange(TRAINING_DATA_KEY, 0, TRAINING_DATA_MAX - 1)
        samples = []
        for r in raw_samples:
            try:
                samples.append(json.loads(r))
            except Exception:
                continue

        if len(samples) < MIN_SAMPLES:
            log.info(f"OnlineLearner: only {len(samples)} samples, skipping retrain")
            return

        X = [s["features"] for s in samples]
        y = [s["label"] for s in samples]

        # Validate feature vector length
        if any(len(x) != len(FEATURE_KEYS) for x in X):
            log.warning("OnlineLearner: feature vector length mismatch, skipping retrain")
            return

        # Walk-forward validation: train on 80%, validate on last 20%
        split = int(len(samples) * 0.8)
        X_train, y_train = X[:split], y[:split]
        X_val,   y_val   = X[split:], y[split:]

        try:
            loop = asyncio.get_event_loop()
            model_bytes = await loop.run_in_executor(
                None, self._predictor.fit, X_train, y_train
            )

            # Compute validation accuracy
            val_acc = 0.0
            if X_val:
                preds = []
                for xv in X_val:
                    fmap = dict(zip(FEATURE_KEYS, xv))
                    score = self._predictor.predict(fmap)
                    preds.append(1 if score > 0.2 else (2 if score < -0.2 else 0))
                val_acc = sum(p == yt for p, yt in zip(preds, y_val)) / len(y_val)

            # Persist model + stats
            version_raw = await redis.get(MODEL_VERSION_KEY)
            version = (int(version_raw) + 1) if version_raw else 1
            await redis.set(MODEL_REDIS_KEY, model_bytes, ex=86400 * 7)
            await redis.set(MODEL_VERSION_KEY, str(version))

            # Feature importance for dashboard
            importance = self._predictor.feature_importance()
            top5 = list(importance.items())[:5]

            stats = {
                "version": version,
                "n_samples": len(samples),
                "val_accuracy": round(val_acc, 4),
                "top_features": top5,
                "timestamp": time.time(),
            }
            await redis.set(STATS_KEY, json.dumps(stats), ex=86400)
            log.info(
                f"ML retrain complete — v{version}, {len(samples)} samples, "
                f"val_acc={val_acc:.1%}, top={top5[0] if top5 else 'n/a'}"
            )

        except Exception as e:
            log.error(f"OnlineLearner retrain failed: {e}")

    async def _load_model(self, redis: aioredis.Redis):
        model_bytes = await redis.get(MODEL_REDIS_KEY)
        if model_bytes:
            version_raw = await redis.get(MODEL_VERSION_KEY)
            version = int(version_raw) if version_raw else 0
            self._predictor.load_bytes(model_bytes, version)
        else:
            log.info("OnlineLearner: no saved model, using heuristic until first retrain")
