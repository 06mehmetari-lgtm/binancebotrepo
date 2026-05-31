from river import drift
import numpy as np

class DriftDetector:
    def __init__(self):
        self.adwin = drift.ADWIN()
        self._ref_dist: np.ndarray | None = None
        self._window: list[float] = []
        self._baseline_mean: float | None = None
        self._baseline_std: float = 1.0

    def update(self, value: float) -> bool:
        self.adwin.update(value)
        self._window.append(value)
        if len(self._window) > 100:
            self._window = self._window[-100:]
        # Simple statistical drift: mean shifted > 2 std from baseline
        stat_drift = False
        if len(self._window) >= 30:
            if self._baseline_mean is None:
                self._baseline_mean = float(np.mean(self._window))
                self._baseline_std = float(np.std(self._window)) or 1.0
            else:
                current_mean = float(np.mean(self._window[-10:]))
                stat_drift = abs(current_mean - self._baseline_mean) > 2 * self._baseline_std
        return self.adwin.drift_detected or stat_drift

    def kl_divergence(self, current_dist: np.ndarray) -> float:
        if self._ref_dist is None:
            self._ref_dist = current_dist
            return 0.0
        p = current_dist + 1e-10
        q = self._ref_dist + 1e-10
        return float(np.sum(p * np.log(p / q)))

    def set_reference(self, dist: np.ndarray):
        self._ref_dist = dist
