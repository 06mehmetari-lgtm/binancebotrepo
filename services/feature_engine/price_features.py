import numpy as np
import pandas as pd

try:
    import pandas_ta as ta
    _HAS_TA = True
except ImportError:
    _HAS_TA = False


class PriceFeatureBuilder:
    def build(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        df = ohlcv.copy()
        df.columns = [c.lower() for c in df.columns]
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        # ─── Returns ───
        df["returns"] = close.pct_change()
        df["log_returns"] = np.log(close / close.shift(1))

        # ─── SMAs ───
        for w in [5, 10, 20, 50, 200]:
            df[f"sma_{w}"] = close.rolling(w).mean()
            df[f"std_{w}"] = close.rolling(w).std()
        df["sma_20_dist"] = (close - df["sma_20"]) / df["sma_20"].replace(0, np.nan)

        # ─── RSI ───
        for p in [7, 14, 21]:
            df[f"rsi_{p}"] = self._rsi(close, p)

        # ─── ATR ───
        df["atr_14"] = self._atr(df, 14)
        df["atr_pct"] = df["atr_14"] / close.replace(0, np.nan) * 100

        # ─── MACD ───
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        df["macd"] = macd_line / close.replace(0, np.nan) * 100
        df["macd_signal"] = macd_signal / close.replace(0, np.nan) * 100
        df["macd_hist"] = (macd_line - macd_signal) / close.replace(0, np.nan) * 100

        # ─── Bollinger Bands ───
        mid = close.rolling(20).mean()
        std = close.rolling(20).std()
        upper = mid + 2 * std
        lower = mid - 2 * std
        bb_range = (upper - lower).replace(0, np.nan)
        df["bb_position"] = (close - lower) / bb_range
        df["bb_squeeze"] = bb_range / mid.replace(0, np.nan) * 100

        # ─── ADX ───
        df["adx_14"] = self._adx(df, 14)

        # ─── Stochastic ───
        low14 = low.rolling(14).min()
        high14 = high.rolling(14).max()
        k = (close - low14) / (high14 - low14).replace(0, np.nan) * 100
        df["stoch_k"] = k
        df["stoch_d"] = k.rolling(3).mean()

        # ─── CCI (Commodity Channel Index) ───
        tp = (high + low + close) / 3
        tp_mean = tp.rolling(20).mean()
        tp_std = tp.rolling(20).std()
        df["cci_20"] = (tp - tp_mean) / (0.015 * tp_std.replace(0, np.nan))

        # ─── Momentum ───
        for p in [5, 10, 20]:
            df[f"mom_{p}"] = (close / close.shift(p) - 1) * 100

        # ─── Rate of Change ───
        df["roc_10"] = (close - close.shift(10)) / close.shift(10).replace(0, np.nan) * 100

        # ─── Williams %R ───
        df["willr_14"] = (high14 - close) / (high14 - low14).replace(0, np.nan) * -100

        # ─── Volume features ───
        avg_vol_20 = volume.rolling(20).mean()
        df["vol_ratio"] = volume / avg_vol_20.replace(0, np.nan)
        df["vol_sma_5"] = volume.rolling(5).mean()
        df["vol_surge"] = (volume > avg_vol_20 * 2).astype(float)

        # ─── OBV ───
        obv = ((close.diff() > 0) * volume - (close.diff() < 0) * volume).cumsum()
        df["obv_change"] = obv.diff(5) / (avg_vol_20.replace(0, np.nan) * 5)

        # ─── Price channel ───
        df["highest_20"] = high.rolling(20).max()
        df["lowest_20"] = low.rolling(20).min()
        channel = (df["highest_20"] - df["lowest_20"]).replace(0, np.nan)
        df["price_channel_pos"] = (close - df["lowest_20"]) / channel

        # ─── Trend strength ───
        df["trend_5_20"] = (df["sma_5"] - df["sma_20"]) / df["sma_20"].replace(0, np.nan) * 100

        # ─── Taker buy (if column available) ───
        if "taker_buy_volume" in df.columns:
            df["taker_buy_ratio"] = df["taker_buy_volume"] / volume.replace(0, np.nan)
        else:
            df["taker_buy_ratio"] = 0.5

        return df.dropna(how="all")

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

    def _adx(self, df: pd.DataFrame, period: int) -> pd.Series:
        high = df["high"]
        low = df["low"]
        close = df["close"]
        plus_dm = (high.diff()).clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        tr = self._atr(df, 1)
        atr = tr.rolling(period).mean()
        plus_di = 100 * plus_dm.rolling(period).mean() / atr.replace(0, np.nan)
        minus_di = 100 * minus_dm.rolling(period).mean() / atr.replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        return dx.rolling(period).mean()
