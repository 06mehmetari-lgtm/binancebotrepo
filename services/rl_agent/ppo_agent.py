import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import EvalCallback, StopTrainingOnNoModelImprovement
from trading_env import TradingEnv


class PPOAgent:
    def __init__(self):
        self.model = None

    def train(
        self,
        features: np.ndarray = None,
        prices: np.ndarray = None,
        total_timesteps: int = 200_000,
    ):
        if features is None:
            # Synthetic: correlated random walk, not i.i.d. Gaussian
            n = 5_000
            returns = np.random.randn(n) * 0.001 + 0.00005  # slight upward drift
            prices = np.cumprod(1 + returns) * 50_000
            features = np.column_stack([
                np.random.randn(n, 20),                      # random market features
                np.cumsum(np.random.randn(n, 10) * 0.1, axis=0),  # trending features
            ]).astype(np.float32)
        if prices is None:
            returns = np.random.randn(len(features)) * 0.001
            prices = np.cumprod(1 + returns) * 50_000

        env = TradingEnv(features, prices)
        self.model = PPO(
            "MlpPolicy", env,
            verbose=0,
            n_steps=512,
            batch_size=64,
            n_epochs=10,
            learning_rate=1e-4,
            ent_coef=0.01,          # entropy bonus: encourage exploration
            clip_range=0.2,
            gamma=0.99,
            gae_lambda=0.95,
        )
        self.model.learn(total_timesteps=total_timesteps)

    def predict(self, obs: np.ndarray) -> tuple[int, float]:
        """Returns (action, confidence). Uses stochastic policy to preserve exploration."""
        if self.model is None:
            return 0, 0.0
        # deterministic=False: sample from policy distribution (exploration)
        action, _states = self.model.predict(obs, deterministic=False)
        # Extract action probability as confidence estimate
        try:
            import torch
            with torch.no_grad():
                obs_t = torch.FloatTensor(obs).unsqueeze(0)
                dist = self.model.policy.get_distribution(obs_t)
                probs = dist.distribution.probs.squeeze().numpy()
                confidence = float(probs[int(action)])
        except Exception:
            confidence = 0.5  # fallback if prob extraction fails
        return int(action), confidence

    def save(self, path: str):
        if self.model:
            self.model.save(path)

    def load(self, path: str):
        self.model = PPO.load(path)
