"""
Multi-Timeframe (MTF) features.
Reads pre-cached 1h klines from Redis and computes higher-timeframe signals.
Confluence: when 1m and 1h agree → higher quality entry.
"""
import json
import numpy as np
import pandas as pd


class MTFFeatureBuilder:
    def build(self, klines_1h_raw: str | None, current_features: dict) -> dict:
        features: dict[str, float] = {}

        if not klines_1h_raw:
            return self._empty()

        try:
            klines = json.loads(klines_1h_raw)
        except Exception:
            return self._empty()

        if len(klines) < 26:
            return self._empty()

        closes  = np.array([float(k["close"])  for k in klines], dtype=np.float64)
        highs   = np.array([float(k["high"])   for k in klines], dtype=np.float64)
        lows    = np.array([float(k["low"])    for k in klines], dtype=np.float64)
        volumes = np.array([float(k["volume"]) for k in klines], dtype=np.float64)

        # ── 1h RSI ──────────────────────────────────────────────────────────
        rsi_1h = self._rsi(closes, 14)
        features["rsi_14_1h"] = float(rsi_1h)

        # ── 1h MACD ─────────────────────────────────────────────────────────
        s = pd.Series(closes)
        ema12 = s.ewm(span=12, adjust=False).mean().iloc[-1]
        ema26 = s.ewm(span=26, adjust=False).mean().iloc[-1]
        macd_line   = ema12 - ema26
        signal_line = pd.Series(closes).ewm(span=12, adjust=False).mean().sub(
                      pd.Series(closes).ewm(span=26, adjust=False).mean()
                      ).ewm(span=9, adjust=False).mean().iloc[-1]
        macd_hist_1h = float((macd_line - signal_line) / max(closes[-1], 1) * 100)
        features["macd_hist_1h"] = float(np.clip(macd_hist_1h, -5, 5))

        # ── 1h trend (EMA20 vs EMA50) ────────────────────────────────────────
        ema20_1h = float(s.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50_1h = float(s.ewm(span=50, adjust=False).mean().iloc[-1]) if len(closes) >= 50 else ema20_1h
        trend_1h = (ema20_1h - ema50_1h) / max(ema50_1h, 1) * 100
        features["trend_1h"] = float(np.clip(trend_1h, -5, 5))

        # ── 1h ATR (normalized) ──────────────────────────────────────────────
        atr_1h = self._atr(highs, lows, closes, 14)
        features["atr_pct_1h"] = float(np.clip(atr_1h / max(closes[-1], 1) * 100, 0, 20))

        # ── Volume trend (is volume increasing on 1h?) ───────────────────────
        vol_ma20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes.mean()
        features["vol_trend_1h"] = float(np.clip(volumes[-1] / max(vol_ma20, 1) - 1, -2, 2))

        # ── Multi-TF Confluence ─────────────────────────────────────────────
        rsi_1m = float(current_features.get("rsi_14", 50))
        macd_1m = float(current_features.get("macd_hist", 0))

        # Bullish confluence: both timeframes agree on bullish
        bull_1m = 1 if rsi_1m < 45 and macd_1m > 0 else 0
        bull_1h = 1 if rsi_1h < 50 and macd_hist_1h > 0 and trend_1h > 0 else 0
        features["bull_confluence"] = float(bull_1m + bull_1h)  # 0, 1, or 2

        # Bearish confluence
        bear_1m = 1 if rsi_1m > 55 and macd_1m < 0 else 0
        bear_1h = 1 if rsi_1h > 50 and macd_hist_1h < 0 and trend_1h < 0 else 0
        features["bear_confluence"] = float(bear_1m + bear_1h)  # 0, 1, or 2

        # Trend alignment score: -1 (bearish align) to +1 (bullish align)
        trend_score = (bull_1m + bull_1h - bear_1m - bear_1h) / 2
        features["trend_alignment"] = float(trend_score)

        # Overbought/oversold on 1h (strong reversal signals)
        features["ob_1h"] = 1.0 if rsi_1h > 70 else 0.0
        features["os_1h"] = 1.0 if rsi_1h < 30 else 0.0

        return features

    def _rsi(self, closes: np.ndarray, period: int) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains  = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100 - 100 / (1 + rs))

    def _atr(self, highs: np.ndarray, lows: np.ndarray,
             closes: np.ndarray, period: int) -> float:
        if len(closes) < 2:
            return 0.0
        hl = highs[1:] - lows[1:]
        hc = np.abs(highs[1:] - closes[:-1])
        lc = np.abs(lows[1:]  - closes[:-1])
        tr = np.maximum(hl, np.maximum(hc, lc))
        return float(np.mean(tr[-period:]))

    def _empty(self) -> dict:
        return {
            "rsi_14_1h": 50.0, "macd_hist_1h": 0.0, "trend_1h": 0.0,
            "atr_pct_1h": 2.0, "vol_trend_1h": 0.0,
            "bull_confluence": 0.0, "bear_confluence": 0.0,
            "trend_alignment": 0.0, "ob_1h": 0.0, "os_1h": 0.0,
        }
