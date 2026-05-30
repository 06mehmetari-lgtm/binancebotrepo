import asyncio
import json
import logging
import os

import numpy as np
import redis.asyncio as aioredis

from ppo_agent import PPOAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOLS_RAW = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
SYMBOLS = [s.strip() for s in SYMBOLS_RAW.split(",") if s.strip()]

RETRAIN_INTERVAL = 6 * 3600  # retrain every 6 hours
MODEL_PATH = "/tmp/ppo_model"

agent = PPOAgent()


async def train_cycle(redis: aioredis.Redis):
    """Train PPO on available feature history."""
    log.info("Starting PPO training cycle")
    try:
        # Collect recent features from Redis for first available symbol
        symbol = SYMBOLS[0]
        features_list = []
        for i in range(500):
            raw = await redis.lindex(f"binance:kline:{symbol.lower()}", i)
            if not raw:
                break
            data = json.loads(raw)
            kline = data.get("data", {}).get("k", {})
            if kline:
                features_list.append([
                    float(kline.get("o", 0)), float(kline.get("h", 0)),
                    float(kline.get("l", 0)), float(kline.get("c", 0)),
                    float(kline.get("v", 0)),
                ])

        if len(features_list) >= 100:
            features = np.array(features_list, dtype=np.float32)
            # Normalize features
            features = (features - features.mean(axis=0)) / (features.std(axis=0) + 1e-8)
            # Pad to 30 features (expected by TradingEnv)
            if features.shape[1] < 30:
                pad = np.zeros((len(features), 30 - features.shape[1]), dtype=np.float32)
                features = np.concatenate([features, pad], axis=1)
            prices = np.array([row[3] for row in features_list])
            agent.train(features=features, prices=prices, total_timesteps=50_000)
            agent.save(MODEL_PATH)
            log.info("PPO training complete, model saved")
        else:
            log.info(f"Insufficient data for PPO training ({len(features_list)} samples), using synthetic")
            agent.train(total_timesteps=50_000)
            agent.save(MODEL_PATH)

        await redis.set("rl:model_ready", "1", ex=RETRAIN_INTERVAL)
    except Exception as e:
        log.error(f"PPO training error: {e}")


async def inference_loop(redis: aioredis.Redis):
    """Continuously generate RL-based signals."""
    model_loaded = False
    while True:
        try:
            if not model_loaded:
                try:
                    agent.load(MODEL_PATH)
                    model_loaded = True
                    log.info("PPO model loaded")
                except Exception:
                    pass

            if model_loaded:
                for symbol in SYMBOLS:
                    feat_raw = await redis.get(f"features:latest:{symbol}")
                    if not feat_raw:
                        continue
                    features = json.loads(feat_raw)
                    numeric_keys = [
                        "rsi_14", "rsi_7", "macd_hist", "bb_position", "atr_14",
                        "adx_14", "imbalance_5", "imbalance_10", "spread_pct",
                        "funding_rate", "oi_change_1h", "ls_ratio_z", "liq_pressure",
                        "fear_greed_norm", "reddit_sentiment", "vix_level",
                    ]
                    obs = np.array([float(features.get(k, 0)) for k in numeric_keys], dtype=np.float32)
                    # Pad to 30 features
                    if len(obs) < 30:
                        obs = np.pad(obs, (0, 30 - len(obs)))
                    action = agent.predict(obs)
                    direction = ["flat", "long", "short"][action]
                    await redis.set(f"rl:signal:{symbol}", json.dumps({
                        "direction": direction, "source": "ppo_rl"
                    }), ex=30)
        except Exception as e:
            log.error(f"PPO inference error: {e}")
        await asyncio.sleep(10)


async def main():
    log.info("rl_agent starting")
    redis = await aioredis.from_url(REDIS_URL)

    # Initial training then periodic retraining
    async def retrain_loop():
        while True:
            await train_cycle(redis)
            await asyncio.sleep(RETRAIN_INTERVAL)

    await asyncio.gather(retrain_loop(), inference_loop(redis))


if __name__ == "__main__":
    asyncio.run(main())
