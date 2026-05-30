import gymnasium as gym
import numpy as np
from gymnasium import spaces

class TradingEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, features: np.ndarray, prices: np.ndarray):
        super().__init__()
        self.features = features
        self.prices = prices
        self.n_steps = len(features)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(features.shape[1],), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)  # 0=hold 1=long 2=short
        self._step = 0
        self._position = 0
        self._entry_price = 0.0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._step = 0
        self._position = 0
        self._entry_price = 0.0
        return self.features[0].astype(np.float32), {}

    def step(self, action: int):
        price = self.prices[self._step]
        reward = self._compute_reward(action, price)
        self._step += 1
        done = self._step >= self.n_steps - 1
        obs = self.features[self._step].astype(np.float32)
        return obs, reward, done, False, {}

    def _compute_reward(self, action: int, price: float) -> float:
        from reward_function import compute_reward
        return compute_reward(action, self._position, price, self._entry_price)
