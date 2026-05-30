import numpy as np
from sklearn.mixture import GaussianMixture

class RegimeClassifier:
    REGIMES = ["trending_up", "trending_down", "ranging", "volatile"]

    def __init__(self, n_components: int = 4):
        self.gmm = GaussianMixture(n_components=n_components, random_state=42)
        self.fitted = False

    def fit(self, features: np.ndarray):
        self.gmm.fit(features)
        self.fitted = True

    def predict(self, features: np.ndarray) -> str:
        if not self.fitted:
            return "unknown"
        label = self.gmm.predict(features)[0]
        return self.REGIMES[label % len(self.REGIMES)]
