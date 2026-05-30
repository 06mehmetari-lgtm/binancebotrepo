from river import drift
import numpy as np
from scipy.stats import entropy

class DriftDetector:
    def __init__(self):
        self.adwin = drift.ADWIN()
        self.ddm = drift.DDM()
        self._ref_dist: np.ndarray | None = None

    def update(self, value: float) -> bool:
        self.adwin.update(value)
        self.ddm.update(int(value > 0))
        return self.adwin.drift_detected or self.ddm.drift_detected

    def kl_divergence(self, current_dist: np.ndarray) -> float:
        if self._ref_dist is None:
            self._ref_dist = current_dist
            return 0.0
        return float(entropy(current_dist + 1e-10, self._ref_dist + 1e-10))

    def set_reference(self, dist: np.ndarray):
        self._ref_dist = dist
