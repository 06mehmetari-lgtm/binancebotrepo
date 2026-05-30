import numpy as np
import pandas as pd

class PriceFeatureBuilder:
    def build(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        df = ohlcv.copy()
        df["returns"] = df["close"].pct_change()
        df["log_returns"] = np.log(df["close"] / df["close"].shift(1))
        for w in [5, 10, 20, 50, 200]:
            df[f"sma_{w}"] = df["close"].rolling(w).mean()
            df[f"std_{w}"] = df["close"].rolling(w).std()
        df["rsi_14"] = self._rsi(df["close"], 14)
        df["atr_14"] = self._atr(df, 14)
        return df.dropna()

    def _rsi(self, series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def _atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        hl = df["high"] - df["low"]
        hc = (df["high"] - df["close"].shift()).abs()
        lc = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return tr.rolling(period).mean()
