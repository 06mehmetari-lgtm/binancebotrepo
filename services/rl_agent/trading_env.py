import gymnasium as gym
import numpy as np
from gymnasium import spaces


class TradingEnv(gym.Env):
    """
    3-action trading environment: 0=hold/flat, 1=long, 2=short.
    _position tracks current state: 0=flat, 1=long, -1=short.
    Reward is realized only on position close; holding incurs small carry cost.
    """
    metadata = {"render_modes": []}

    def __init__(self, features: np.ndarray, prices: np.ndarray):
        super().__init__()
        self.features = features.astype(np.float32)
        self.prices = prices.astype(np.float64)
        self.n_steps = len(features)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(features.shape[1],), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)
        self._step = 0
        self._position = 0       # 0=flat, 1=long, -1=short
        self._entry_price = 0.0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._step = 0
        self._position = 0
        self._entry_price = 0.0
        return self.features[0].copy(), {}

    def step(self, action: int):
        price = float(self.prices[self._step])
        reward = self._compute_reward(action, price)

        # Update position state AFTER computing reward
        if action == 1 and self._position == 0:     # enter long
            self._position = 1
            self._entry_price = price
        elif action == 2 and self._position == 0:   # enter short
            self._position = -1
            self._entry_price = price
        elif action == 0 and self._position != 0:   # close position
            self._position = 0
            self._entry_price = 0.0

        self._step += 1
        done = self._step >= self.n_steps - 1

        # Guard against out-of-bounds when episode is done
        obs_idx = min(self._step, self.n_steps - 1)
        obs = self.features[obs_idx].copy()
        return obs, reward, done, False, {}

    def _compute_reward(self, action: int, price: float) -> float:
        from reward_function import compute_reward
        return compute_reward(action, self._position, price, self._entry_price)
