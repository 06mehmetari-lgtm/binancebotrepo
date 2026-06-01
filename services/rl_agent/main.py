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
_last_retrain = 0.0


def extract_obs(features: dict) -> np.ndarray:
    obs = np.array([float(features.get(k, 0) or 0) for k in NUMERIC_KEYS], dtype=np.float32)
    if len(obs) < OBS_DIM:
        obs = np.pad(obs, (0, OBS_DIM - len(obs)))
    return obs


async def train_cycle(redis: aioredis.Redis):
    global _last_retrain
    log.info(f"Starting PPO training cycle — buffer size: {len(_feature_buffer)}")
    try:
        if len(_feature_buffer) >= 200:
            buffer_list = list(_feature_buffer)
            features = np.array([item[0] for item in buffer_list], dtype=np.float32)
            prices = np.array([item[1] for item in buffer_list], dtype=np.float32)

            # Normalize features per column
            mean = features.mean(axis=0)
            std = features.std(axis=0) + 1e-8
            features = (features - mean) / std

            agent.train(features=features, prices=prices, total_timesteps=50_000)
            agent.save(MODEL_PATH)
            log.info(f"PPO training complete on {len(buffer_list)} real observations")
        else:
            # Fallback to synthetic training if insufficient real data
            log.info(f"Insufficient buffer data ({len(_feature_buffer)} < 200), using synthetic training")
            agent.train(total_timesteps=50_000)
            agent.save(MODEL_PATH)

        _last_retrain = time.time()
        await redis.set("rl:model_ready", "1", ex=RETRAIN_INTERVAL)
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
                    # confidence = actual policy probability from PPO distribution

                    await redis.set(f"rl:signal:{symbol}", json.dumps({
                        "direction": direction,
                        "confidence": confidence,
                        "source": "ppo_rl",
                        "timestamp": time.time(),
                    }), ex=30)

                    # Accumulate to training buffer
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

    async def retrain_loop():
        # Give the inference loop time to accumulate real data before first training
        await asyncio.sleep(300)
        while True:
            await train_cycle(redis)
            await asyncio.sleep(RETRAIN_INTERVAL)

    await asyncio.gather(retrain_loop(), inference_loop(redis))


if __name__ == "__main__":
    asyncio.run(main())
