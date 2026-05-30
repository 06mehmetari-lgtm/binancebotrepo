import numpy as np
import shap
from sklearn.ensemble import GradientBoostingClassifier

class FeatureSelector:
    def __init__(self, top_k: int = 20):
        self.top_k = top_k
        self.selected_features: list[str] = []

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: list[str]):
        model = GradientBoostingClassifier(n_estimators=50, max_depth=3)
        model.fit(X, y)
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)
        importance = np.abs(shap_values).mean(axis=0)
        idx = np.argsort(importance)[::-1][:self.top_k]
        self.selected_features = [feature_names[i] for i in idx]
        return self

    def transform(self, X: np.ndarray, feature_names: list[str]) -> np.ndarray:
        idx = [feature_names.index(f) for f in self.selected_features if f in feature_names]
        return X[:, idx]
