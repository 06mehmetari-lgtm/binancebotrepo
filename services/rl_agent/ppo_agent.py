import numpy as np
from stable_baselines3 import PPO
from trading_env import TradingEnv

class PPOAgent:
    def __init__(self):
        self.model = None

    def train(self, features: np.ndarray = None, prices: np.ndarray = None,
              total_timesteps: int = 500_000):
        if features is None:
            features = np.random.randn(10_000, 30).astype(np.float32)
        if prices is None:
            prices = np.cumprod(1 + np.random.randn(10_000) * 0.001) * 50_000

        env = TradingEnv(features, prices)
        self.model = PPO("MlpPolicy", env, verbose=1, n_steps=2048,
                         batch_size=64, learning_rate=3e-4)
        self.model.learn(total_timesteps=total_timesteps)

    def predict(self, obs: np.ndarray) -> int:
        if self.model is None:
            return 0
        action, _ = self.model.predict(obs, deterministic=True)
        return int(action)

    def save(self, path: str):
        if self.model:
            self.model.save(path)

    def load(self, path: str):
        self.model = PPO.load(path)
