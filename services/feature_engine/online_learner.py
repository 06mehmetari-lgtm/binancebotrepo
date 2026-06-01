"""
Online Learner — Phase 3 (corrected).
Watches ml:training_data list (filled by feedback_writer in autopsy service).
When enough new labeled samples arrive, retrains the sklearn GradientBoosting model
and persists it to Redis so all services pick it up.

Data flow:
  shadow_system closes trade
      → ch:trade_closed (with regime + agent_votes)
      → autopsy/feedback_writer.write_feedback()
      → LPUSH ml:training_data  ← we watch this
      → retrain here every RETRAIN_EVERY new samples
      → ml:model:v2  (feature_engine ml_predictor reloads this every 10 min)
"""
import asyncio
import json
import logging
import time

import redis.asyncio as aioredis

from ml_signal import MLSignalPredictor, FEATURE_KEYS, MODEL_REDIS_KEY

log = logging.getLogger(__name__)

TRAINING_DATA_KEY = "ml:training_data"
RETRAIN_EVERY     = 50    # retrain when this many new samples have arrived
MIN_SAMPLES       = 60    # don't train with fewer than this
POLL_INTERVAL     = 60    # seconds between list-length checks
STATS_KEY         = "ml:learner:stats"
MODEL_VERSION_KEY = "ml:model:version"


class OnlineLearner:
    def __init__(self, predictor: MLSignalPredictor):
        self._predictor            = predictor
        self._last_known_count: int = 0

    async def run(self, redis: aioredis.Redis):
        log.info("OnlineLearner started — polling ml:training_data every 60s")
        await self._load_model(redis)
        # Initialise counter so we don't immediately retrain on stale data
        self._last_known_count = await redis.llen(TRAINING_DATA_KEY)

        while True:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                await self._check_and_retrain(redis)
            except Exception as e:
                log.error(f"OnlineLearner poll error: {e}")

    async def _check_and_retrain(self, redis: aioredis.Redis):
        current_count = await redis.llen(TRAINING_DATA_KEY)
        new_samples   = current_count - self._last_known_count

        if new_samples < RETRAIN_EVERY:
            return

        log.info(
            f"OnlineLearner: {new_samples} new samples "
            f"(total={current_count}) — starting retrain"
        )
        await self._retrain(redis)
        self._last_known_count = current_count

    async def _retrain(self, redis: aioredis.Redis):
        raw_list = await redis.lrange(TRAINING_DATA_KEY, 0, -1)
        samples: list[dict] = []
        for r in raw_list:
            try:
                samples.append(json.loads(r))
            except Exception:
                continue

        if len(samples) < MIN_SAMPLES:
            log.info(f"OnlineLearner: only {len(samples)} samples, need {MIN_SAMPLES} — skipping")
            return

        X, y = [], []
        for s in samples:
            vec = s.get("features", [])
            lbl = s.get("label")
            if len(vec) == len(FEATURE_KEYS) and lbl is not None:
                X.append(vec)
                y.append(lbl)

        if len(X) < MIN_SAMPLES:
            log.warning(
                f"OnlineLearner: only {len(X)} valid feature vectors "
                f"(expected len={len(FEATURE_KEYS)}) — skipping"
            )
            return

        # Walk-forward: train on first 80%, validate on last 20%
        split   = max(MIN_SAMPLES, int(len(X) * 0.8))
        X_train, y_train = X[:split], y[:split]
        X_val,   y_val   = X[split:], y[split:]

        try:
            loop = asyncio.get_event_loop()
            model_bytes = await loop.run_in_executor(
                None, self._predictor.fit, X_train, y_train
            )

            # Validation accuracy
            val_acc = 0.0
            if X_val:
                correct = 0
                for xv, yt in zip(X_val, y_val):
                    fmap  = dict(zip(FEATURE_KEYS, xv))
                    score = self._predictor.predict(fmap)
                    pred  = 1 if score > 0.2 else (2 if score < -0.2 else 0)
                    if pred == yt:
                        correct += 1
                val_acc = correct / len(y_val)

            # Persist to Redis
            version_raw = await redis.get(MODEL_VERSION_KEY)
            version     = (int(version_raw) + 1) if version_raw else 1
            await redis.set(MODEL_REDIS_KEY, model_bytes, ex=86400 * 7)
            await redis.set(MODEL_VERSION_KEY, str(version))

            # Feature importance
            importance = self._predictor.feature_importance()
            top5       = list(importance.items())[:5]

            # Label distribution for diagnostics
            from collections import Counter
            label_dist = dict(Counter(y))

            stats = {
                "version":      version,
                "n_samples":    len(X),
                "val_accuracy": round(val_acc, 4),
                "top_features": top5,
                "label_dist":   label_dist,
                "timestamp":    time.time(),
            }
            await redis.set(STATS_KEY, json.dumps(stats), ex=86400)

            log.info(
                f"OnlineLearner retrain complete — "
                f"v{version}, {len(X)} samples, val_acc={val_acc:.1%}, "
                f"labels={label_dist}, top_feature={top5[0][0] if top5 else 'n/a'}"
            )

        except Exception as e:
            log.error(f"OnlineLearner retrain failed: {e}")

    async def _load_model(self, redis: aioredis.Redis):
        model_bytes = await redis.get(MODEL_REDIS_KEY)
        if model_bytes:
            version_raw = await redis.get(MODEL_VERSION_KEY)
            version     = int(version_raw) if version_raw else 0
            self._predictor.load_bytes(model_bytes, version)
            log.info(f"OnlineLearner: loaded existing model v{version}")
        else:
            log.info("OnlineLearner: no saved model — using heuristic scoring until first retrain")
