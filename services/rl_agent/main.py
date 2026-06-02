import asyncio
import json
import logging
import os
import time
from collections import deque

import numpy as np
import redis.asyncio as aioredis

from ppo_agent import PPOAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
RETRAIN_INTERVAL = 6 * 3600  # retrain every 6 hours
MODEL_PATH = "/app/ppo_model"  # persistent path, not /tmp

agent = PPOAgent()

# Feature keys used for observations (must match training)
NUMERIC_KEYS = [
    "rsi_14", "rsi_7", "macd_hist", "bb_position", "atr_14",
    "adx_14", "imbalance_5", "imbalance_10", "spread_pct",
    "funding_rate", "oi_change_1h", "ls_ratio_z", "liq_pressure",
    "fear_greed_norm", "reddit_sentiment", "vix_level",
]
OBS_DIM = 30  # padded observation size

# Rolling buffer: stores (obs_vector, approx_price) tuples for training
_feature_buffer: deque = deque(maxlen=5000)
# Labeled buffer: stores (obs_vector, pnl_pct) from real trade outcomes
_labeled_buffer: deque = deque(maxlen=2000)
_last_retrain = 0.0


def extract_obs(features: dict) -> np.ndarray:
    obs = np.array([float(features.get(k, 0) or 0) for k in NUMERIC_KEYS], dtype=np.float32)
    if len(obs) < OBS_DIM:
        obs = np.pad(obs, (0, OBS_DIM - len(obs)))
    return obs


async def trade_feedback_loop(redis: aioredis.Redis):
    """Subscribe to closed trades; store labeled training samples with real outcomes."""
    pubsub = redis.pubsub()
    await pubsub.subscribe("ch:trade_closed")
    log.info("RL agent: subscribed to ch:trade_closed for feedback learning")
    async for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        try:
            trade = json.loads(msg["data"])
            symbol = trade.get("symbol", "")
            pnl_pct = float(trade.get("pnl_pct", 0))
            # Load the feature snapshot captured at signal time
            feat_raw = await redis.get(f"ml:entry_features:{symbol}")
            if not feat_raw:
                continue
            features = json.loads(feat_raw)
            obs = extract_obs(features)
            _labeled_buffer.append((obs, pnl_pct))
            log.info(f"RL feedback: {symbol} pnl={pnl_pct:.3f}% — labeled buffer size={len(_labeled_buffer)}")
        except Exception as e:
            log.error(f"RL feedback error: {e}")


async def train_cycle(redis: aioredis.Redis):
    global _last_retrain
    try:
        # Prefer labeled trade-outcome data over unlabeled feature buffer
        if len(_labeled_buffer) >= 50:
            labeled = list(_labeled_buffer)
            features_arr = np.array([item[0] for item in labeled], dtype=np.float32)
            pnl_arr = np.array([item[1] for item in labeled], dtype=np.float32)
            # Synthetic price series: PPO learns which states lead to positive returns
            prices = 50_000.0 * np.cumprod(1 + np.clip(pnl_arr / 100.0, -0.10, 0.10))
            mean = features_arr.mean(axis=0)
            std = features_arr.std(axis=0) + 1e-8
            features_arr = (features_arr - mean) / std
            timesteps = min(50_000, max(10_000, len(labeled) * 200))
            agent.train(features=features_arr, prices=prices, total_timesteps=timesteps)
            agent.save(MODEL_PATH)
            log.info(f"PPO trained on {len(labeled)} labeled trade outcomes (timesteps={timesteps})")
        elif len(_feature_buffer) >= 200:
            buffer_list = list(_feature_buffer)
            features_arr = np.array([item[0] for item in buffer_list], dtype=np.float32)
            prices = np.array([item[1] for item in buffer_list], dtype=np.float32)
            mean = features_arr.mean(axis=0)
            std = features_arr.std(axis=0) + 1e-8
            features_arr = (features_arr - mean) / std
            agent.train(features=features_arr, prices=prices, total_timesteps=50_000)
            agent.save(MODEL_PATH)
            log.info(f"PPO trained on {len(buffer_list)} unlabeled observations")
        else:
            log.info(f"Insufficient data (labeled={len(_labeled_buffer)}, feature={len(_feature_buffer)}), using synthetic")
            agent.train(total_timesteps=50_000)
            agent.save(MODEL_PATH)

        _last_retrain = time.time()
        await redis.set("rl:model_ready", "1", ex=RETRAIN_INTERVAL)
        await redis.set("rl:labeled_samples", str(len(_labeled_buffer)), ex=86400)
    except Exception as e:
        log.error(f"PPO training error: {e}")


async def inference_loop(redis: aioredis.Redis):
    model_loaded = False
    while True:
        try:
            if not model_loaded:
                try:
                    agent.load(MODEL_PATH)
                    model_loaded = True
                    log.info("PPO model loaded from disk")
                except Exception:
                    pass

            if model_loaded:
                keys = await redis.keys("features:latest:*")
                for key in keys:
                    feat_raw = await redis.get(key)
                    if not feat_raw:
                        continue
                    features = json.loads(feat_raw)
                    symbol = (key.decode() if isinstance(key, bytes) else key).split(":")[-1]

                    obs = extract_obs(features)
                    action, confidence = agent.predict(obs)
                    direction = ["flat", "long", "short"][action]

                    await redis.set(f"rl:signal:{symbol}", json.dumps({
                        "direction": direction,
                        "confidence": confidence,
                        "source": "ppo_rl",
                        "timestamp": time.time(),
                    }), ex=30)

                    # Accumulate to unlabeled training buffer
                    price_raw = await redis.get(f"binance:ticker:{symbol.lower()}")
                    if price_raw:
                        ticker = json.loads(price_raw)
                        price = float(ticker.get("data", ticker).get("b", 0))
                        if price > 0:
                            _feature_buffer.append((obs, price))

        except Exception as e:
            log.error(f"PPO inference error: {e}")
        await asyncio.sleep(10)


async def main():
    log.info("rl_agent starting")
    redis = await aioredis.from_url(REDIS_URL)
    redis_sub = await aioredis.from_url(REDIS_URL)

    async def retrain_loop():
        await asyncio.sleep(300)
        while True:
            await train_cycle(redis)
            await asyncio.sleep(RETRAIN_INTERVAL)

    await asyncio.gather(
        retrain_loop(),
        inference_loop(redis),
        trade_feedback_loop(redis_sub),
    )


if __name__ == "__main__":
    asyncio.run(main())
