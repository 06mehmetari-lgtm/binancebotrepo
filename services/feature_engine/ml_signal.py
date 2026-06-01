"""
ML Signal Predictor — Phase 2.
Sklearn GradientBoosting model trained on labeled trade outcomes.
Falls back to heuristic scoring when no trained model exists.
Model bytes stored in Redis so all services share the same version.
"""
import logging
import pickle
import numpy as np

log = logging.getLogger(__name__)

# Canonical feature vector order — must match online_learner.py
FEATURE_KEYS = [
    # 1m price
    "rsi_14", "rsi_7", "macd_hist", "bb_position", "atr_pct",
    "ema_trend", "volume_ratio", "adx_14", "imbalance_5",
    # CVD / order flow
    "cvd_5m", "cvd_15m", "cvd_1h", "buy_ratio_5m",
    "cvd_acceleration", "whale_buy_ratio",
    # Liquidations
    "liq_long_1h", "liq_short_1h", "liq_ratio_1h", "liq_usd_1h",
    # Volume profile
    "vpoc_dist_pct", "vah_dist_pct", "val_dist_pct",
    "in_value_area", "vpoc_dominance", "va_position",
    # MTF (1h)
    "rsi_14_1h", "macd_hist_1h", "trend_1h", "atr_pct_1h", "vol_trend_1h",
    "bull_confluence", "bear_confluence", "trend_alignment", "ob_1h", "os_1h",
]

# Label encoding: 1=long, 0=flat/no-signal, -1=short (binary within direction)
# Training labels: 1=winning trade direction, 0=losing trade direction
MODEL_REDIS_KEY = "ml:model:v2"
SCORE_CLIP = 1.0


class MLSignalPredictor:
    def __init__(self):
        self._model = None       # sklearn Pipeline
        self._model_version = 0
        self._n_predictions = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def predict(self, features: dict) -> float:
        """Return score in [-1, +1]. Positive = bullish, negative = bearish."""
        vec = self.extract_vector(features)
        if self._model is not None:
            try:
                proba = self._model.predict_proba([vec])[0]
                # Classes: 0=short_win, 1=flat/neutral, 2=long_win
                # Score = long_win_prob - short_win_prob
                if len(proba) == 3:
                    score = float(proba[2] - proba[0])
                else:
                    score = float(proba[-1] * 2 - 1)
                self._n_predictions += 1
                return float(np.clip(score, -SCORE_CLIP, SCORE_CLIP))
            except Exception as e:
                log.debug(f"ML predict error: {e}")
        return self._heuristic(features)

    def extract_vector(self, features: dict) -> list[float]:
        return [float(features.get(k, 0) or 0) for k in FEATURE_KEYS]

    def load_bytes(self, model_bytes: bytes, version: int = 0):
        try:
            self._model = pickle.loads(model_bytes)
            self._model_version = version
            log.info(f"ML model loaded — version {version}, {len(FEATURE_KEYS)} features")
        except Exception as e:
            log.warning(f"ML model load failed: {e}")

    def fit(self, X: list[list[float]], y: list[int]) -> bytes:
        """Train a new model. Returns pickle bytes for Redis storage."""
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline

        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", GradientBoostingClassifier(
                n_estimators=200, max_depth=4,
                learning_rate=0.05, subsample=0.8,
                random_state=42,
            )),
        ])
        pipe.fit(X, y)
        self._model = pipe
        self._model_version += 1
        model_bytes = pickle.dumps(pipe)
        classes = list(pipe.classes_)
        log.info(
            f"ML model trained — {len(X)} samples, classes={classes}, "
            f"version={self._model_version}"
        )
        return model_bytes

    def feature_importance(self) -> dict[str, float]:
        if self._model is None:
            return {}
        try:
            clf = self._model.named_steps["clf"]
            importances = clf.feature_importances_
            return dict(sorted(
                zip(FEATURE_KEYS, importances),
                key=lambda x: x[1], reverse=True,
            ))
        except Exception:
            return {}

    # ── Heuristic fallback (no trained model) ────────────────────────────────

    def _heuristic(self, f: dict) -> float:
        rsi      = float(f.get("rsi_14", 50))
        macd     = float(f.get("macd_hist", 0))
        cvd_5m   = float(f.get("cvd_5m", 0))
        trend_al = float(f.get("trend_alignment", 0))
        va_pos   = float(f.get("va_position", 0))
        liq_rat  = float(f.get("liq_ratio_1h", 0))
        rsi_1h   = float(f.get("rsi_14_1h", 50))
        bull_c   = float(f.get("bull_confluence", 0))
        bear_c   = float(f.get("bear_confluence", 0))

        score = 0.0
        score += (50 - rsi) / 100          # oversold → positive
        score += (50 - rsi_1h) / 100 * 0.5
        score += macd * 8
        score += cvd_5m * 0.35
        score += trend_al * 0.25
        score -= va_pos * 0.15             # at premium → bearish
        score += liq_rat * 0.15
        score += (bull_c - bear_c) * 0.1

        return float(np.clip(score, -SCORE_CLIP, SCORE_CLIP))
