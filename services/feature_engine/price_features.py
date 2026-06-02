"""
Price Feature Builder — 60+ teknik indikatör (tamamen sıfırdan hesaplanır, harici kütüphane yok).

Katmanlar:
  1. Trend    : SMA, EMA (9/20/50/200), HMA, Supertrend, Parabolic SAR, Donchian, Ichimoku
  2. Momentum : RSI (7/14/21), MACD, Stochastic, CCI, ROC, Williams %R
  3. Güç/Yön  : ADX, DI+/DI-, Aroon (25), Vortex (14)
  4. Hacim    : OBV, VWAP, A/D Line, CMF (20), MFI (14)
  5. Volatilite: ATR, Bollinger Bands, Donchian genişliği
"""
import numpy as np
import pandas as pd


class PriceFeatureBuilder:
    def build(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        df = ohlcv.copy()
        df.columns = [c.lower() for c in df.columns]
        close  = df["close"]
        high   = df["high"]
        low    = df["low"]
        volume = df["volume"]
        open_  = df["open"]

        # ── Returns ────────────────────────────────────────────────────────────
        df["returns"]     = close.pct_change()
        df["log_returns"] = np.log(close / close.shift(1))

        # ── SMAs ───────────────────────────────────────────────────────────────
        for w in [5, 10, 20, 50, 200]:
            df[f"sma_{w}"] = close.rolling(w).mean()
            df[f"std_{w}"] = close.rolling(w).std()
        df["sma_20_dist"] = (close - df["sma_20"]) / df["sma_20"].replace(0, np.nan)

        # ── EMAs (9, 20, 50, 200) ──────────────────────────────────────────────
        for span in [9, 20, 50, 200]:
            df[f"ema_{span}"] = close.ewm(span=span, adjust=False).mean()
        df["ema_20_dist"]      = (close - df["ema_20"]) / df["ema_20"].replace(0, np.nan)
        df["ema_50_200_cross"] = (df["ema_50"] - df["ema_200"]) / df["ema_200"].replace(0, np.nan) * 100
        df["ema_20_50_cross"]  = (df["ema_20"] - df["ema_50"]) / df["ema_50"].replace(0, np.nan) * 100
        df["price_above_ema200"] = (close > df["ema_200"]).astype(float)

        # ── HMA (Hull Moving Average, period=16) ───────────────────────────────
        df["hma_16"] = self._hma(close, 16)

        # ── ATR ────────────────────────────────────────────────────────────────
        df["atr_14"]  = self._atr(df, 14)
        df["atr_pct"] = df["atr_14"] / close.replace(0, np.nan) * 100

        # ── RSI ────────────────────────────────────────────────────────────────
        for p in [7, 14, 21]:
            df[f"rsi_{p}"] = self._rsi(close, p)

        # ── MACD ───────────────────────────────────────────────────────────────
        ema12       = close.ewm(span=12, adjust=False).mean()
        ema26       = close.ewm(span=26, adjust=False).mean()
        macd_line   = ema12 - ema26
        macd_sig    = macd_line.ewm(span=9, adjust=False).mean()
        df["macd"]        = macd_line / close.replace(0, np.nan) * 100
        df["macd_signal"] = macd_sig  / close.replace(0, np.nan) * 100
        df["macd_hist"]   = (macd_line - macd_sig) / close.replace(0, np.nan) * 100

        # ── Bollinger Bands ────────────────────────────────────────────────────
        bb_mid   = close.rolling(20).mean()
        bb_std   = close.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_range = (bb_upper - bb_lower).replace(0, np.nan)
        df["bb_position"] = (close - bb_lower) / bb_range
        df["bb_squeeze"]  = bb_range / bb_mid.replace(0, np.nan) * 100
        df["bb_upper"]    = bb_upper
        df["bb_lower"]    = bb_lower

        # ── ADX + DI+ / DI- ───────────────────────────────────────────────────
        adx, di_plus, di_minus = self._adx_full(df, 14)
        df["adx_14"]    = adx
        df["di_plus"]   = di_plus
        df["di_minus"]  = di_minus
        df["di_cross"]  = di_plus - di_minus   # >0 = bullish pressure

        # ── Stochastic ────────────────────────────────────────────────────────
        low14  = low.rolling(14).min()
        high14 = high.rolling(14).max()
        k      = (close - low14) / (high14 - low14).replace(0, np.nan) * 100
        df["stoch_k"] = k
        df["stoch_d"] = k.rolling(3).mean()

        # ── CCI ───────────────────────────────────────────────────────────────
        tp      = (high + low + close) / 3
        tp_mean = tp.rolling(20).mean()
        tp_std  = tp.rolling(20).std()
        df["cci_20"] = (tp - tp_mean) / (0.015 * tp_std.replace(0, np.nan))

        # ── Momentum ──────────────────────────────────────────────────────────
        for p in [5, 10, 20]:
            df[f"mom_{p}"] = (close / close.shift(p) - 1) * 100

        # ── Rate of Change ────────────────────────────────────────────────────
        df["roc_10"] = (close - close.shift(10)) / close.shift(10).replace(0, np.nan) * 100

        # ── Williams %R ───────────────────────────────────────────────────────
        df["willr_14"] = (high14 - close) / (high14 - low14).replace(0, np.nan) * -100

        # ── Aroon (25) ─────────────────────────────────────────────────────────
        df["aroon_up"], df["aroon_down"] = self._aroon(high, low, 25)
        df["aroon_osc"] = df["aroon_up"] - df["aroon_down"]   # >0 = bullish trend dominance

        # ── Vortex (14) ────────────────────────────────────────────────────────
        df["vi_plus"], df["vi_minus"] = self._vortex(high, low, close, 14)
        df["vi_diff"] = df["vi_plus"] - df["vi_minus"]        # >0 = bullish flow

        # ── Supertrend (period=10, multiplier=3.0) ────────────────────────────
        st, st_dir = self._supertrend(high, low, close, 10, 3.0)
        df["supertrend"]      = st
        df["supertrend_dir"]  = st_dir   # 1=bullish, -1=bearish
        df["supertrend_dist"] = (close - st) / df["atr_14"].replace(0, np.nan)

        # ── Parabolic SAR ─────────────────────────────────────────────────────
        psar, psar_bull = self._parabolic_sar(high, low, close)
        df["psar"]      = psar
        df["psar_bull"] = psar_bull       # 1=bullish (price above SAR), 0=bearish
        df["psar_dist"] = (close - psar) / df["atr_14"].replace(0, np.nan)

        # ── Donchian Channel (20) ─────────────────────────────────────────────
        dc_high = high.rolling(20).max()
        dc_low  = low.rolling(20).min()
        dc_rng  = (dc_high - dc_low).replace(0, np.nan)
        df["donchian_pos"]   = (close - dc_low) / dc_rng     # 0=bottom, 1=top
        df["donchian_width"] = dc_rng / close.replace(0, np.nan) * 100

        # ── Ichimoku Cloud ────────────────────────────────────────────────────
        tenkan   = (high.rolling(9).max()  + low.rolling(9).min())  / 2
        kijun    = (high.rolling(26).max() + low.rolling(26).min()) / 2
        senkou_a = (tenkan + kijun) / 2
        senkou_b = (high.rolling(52).max() + low.rolling(52).min()) / 2
        # Cloud is projected 26 bars ahead; we read the cloud FROM 26 bars ago
        cloud_top = pd.concat([senkou_a.shift(26), senkou_b.shift(26)], axis=1).max(axis=1)
        cloud_bot = pd.concat([senkou_a.shift(26), senkou_b.shift(26)], axis=1).min(axis=1)
        df["ichi_tenkan"]          = tenkan
        df["ichi_kijun"]           = kijun
        df["ichi_tk_cross"]        = (tenkan - kijun) / close.replace(0, np.nan) * 100   # >0 bullish
        df["ichi_cloud_thick"]     = (cloud_top - cloud_bot) / close.replace(0, np.nan) * 100
        # Price relative to cloud: +1 above, 0 inside, -1 below
        df["ichi_price_vs_cloud"]  = np.where(close > cloud_top,  1.0,
                                     np.where(close < cloud_bot, -1.0, 0.0))
        # Chikou vs price 26 bars ago
        df["ichi_chikou_signal"]   = (close - close.shift(26)) / close.shift(26).replace(0, np.nan) * 100

        # ── VWAP (rolling 500-period = full available session) ────────────────
        tp_vwap = (high + low + close) / 3
        df["vwap"]            = (tp_vwap * volume).rolling(500, min_periods=1).sum() \
                              / volume.rolling(500, min_periods=1).sum().replace(0, np.nan)
        df["vwap_dist"]       = (close - df["vwap"]) / df["atr_14"].replace(0, np.nan)
        df["price_above_vwap"] = (close > df["vwap"]).astype(float)

        # ── A/D Line (Accumulation / Distribution) ────────────────────────────
        hl_range = (high - low).replace(0, np.nan)
        clv      = ((close - low) - (high - close)) / hl_range
        adl      = (clv * volume).cumsum()
        avg_vol20 = volume.rolling(20).mean()
        df["adl_change"] = adl.diff(5) / (avg_vol20.replace(0, np.nan) * 5)

        # ── CMF (Chaikin Money Flow, 20) ──────────────────────────────────────
        mf_vol   = clv * volume
        df["cmf_20"] = mf_vol.rolling(20).sum() / volume.rolling(20).sum().replace(0, np.nan)

        # ── MFI (Money Flow Index, 14) ────────────────────────────────────────
        df["mfi_14"] = self._mfi(high, low, close, volume, 14)

        # ── OBV ───────────────────────────────────────────────────────────────
        obv = ((close.diff() > 0) * volume - (close.diff() < 0) * volume).cumsum()
        df["obv_change"] = obv.diff(5) / (avg_vol20.replace(0, np.nan) * 5)

        # ── Volume features ───────────────────────────────────────────────────
        df["vol_ratio"] = volume / avg_vol20.replace(0, np.nan)
        df["vol_sma_5"] = volume.rolling(5).mean()
        df["vol_surge"] = (volume > avg_vol20 * 2).astype(float)

        # ── Price channel (historical highest/lowest 20) ───────────────────────
        df["highest_20"] = high.rolling(20).max()
        df["lowest_20"]  = low.rolling(20).min()
        channel          = (df["highest_20"] - df["lowest_20"]).replace(0, np.nan)
        df["price_channel_pos"] = (close - df["lowest_20"]) / channel

        # ── Trend strength (SMA cross) ────────────────────────────────────────
        df["trend_5_20"] = (df["sma_5"] - df["sma_20"]) / df["sma_20"].replace(0, np.nan) * 100

        # ── Taker buy ─────────────────────────────────────────────────────────
        if "taker_buy_volume" in df.columns:
            df["taker_buy_ratio"] = df["taker_buy_volume"] / volume.replace(0, np.nan)
        else:
            df["taker_buy_ratio"] = 0.5

        return df.dropna(how="all")

    # ──────────────────────────── Indicator helpers ───────────────────────────

    def _rsi(self, series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def _atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        hl = df["high"] - df["low"]
        hc = (df["high"] - df["close"].shift()).abs()
        lc = (df["low"]  - df["close"].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def _atr_np(self, h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int) -> np.ndarray:
        """Numpy ATR — used by iterative indicators."""
        n  = len(c)
        tr = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        atr = np.zeros(n)
        for i in range(period, n):
            atr[i] = np.mean(tr[i - period + 1: i + 1])
        return atr

    def _adx_full(self, df: pd.DataFrame, period: int) -> tuple[pd.Series, pd.Series, pd.Series]:
        high     = df["high"]
        low      = df["low"]
        plus_dm  = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        # Only the larger DM counts
        cond     = plus_dm >= minus_dm
        plus_dm  = plus_dm.where(cond, 0.0)
        minus_dm = minus_dm.where(~cond, 0.0)
        atr      = self._atr(df, period)
        plus_di  = 100 * plus_dm.rolling(period).mean()  / atr.replace(0, np.nan)
        minus_di = 100 * minus_dm.rolling(period).mean() / atr.replace(0, np.nan)
        dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx      = dx.rolling(period).mean()
        return adx, plus_di, minus_di

    def _hma(self, close: pd.Series, n: int) -> pd.Series:
        """Hull Moving Average = WMA( 2×WMA(n/2) - WMA(n), √n )"""
        n2   = max(1, n // 2)
        sqn  = max(1, int(round(np.sqrt(n))))
        wma_n  = self._wma(close, n)
        wma_n2 = self._wma(close, n2)
        raw    = 2.0 * wma_n2 - wma_n
        return self._wma(raw, sqn)

    def _wma(self, series: pd.Series, period: int) -> pd.Series:
        weights = np.arange(1, period + 1, dtype=float)
        w_sum   = weights.sum()
        return series.rolling(period).apply(
            lambda x: float(np.dot(x, weights) / w_sum), raw=True
        )

    def _aroon(self, high: pd.Series, low: pd.Series,
               period: int) -> tuple[pd.Series, pd.Series]:
        """Aroon Up/Down — time-based trend strength (0-100)."""
        h = high.values
        l = low.values
        n = len(h)
        aroon_up   = np.full(n, np.nan)
        aroon_down = np.full(n, np.nan)
        for i in range(period, n):
            window_h = h[i - period: i + 1]   # length = period+1
            window_l = l[i - period: i + 1]
            # argmax gives 0=oldest, period=newest
            aroon_up[i]   = (float(np.argmax(window_h)) / period) * 100.0
            aroon_down[i] = (float(np.argmin(window_l)) / period) * 100.0
        return pd.Series(aroon_up, index=high.index), pd.Series(aroon_down, index=low.index)

    def _vortex(self, high: pd.Series, low: pd.Series, close: pd.Series,
                period: int) -> tuple[pd.Series, pd.Series]:
        """Vortex Indicator VI+ / VI- — flow direction strength."""
        vm_plus  = (high - low.shift(1)).abs()
        vm_minus = (low  - high.shift(1)).abs()
        hl = high - low
        hc = (high - close.shift(1)).abs()
        lc = (low  - close.shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        tr_sum     = tr.rolling(period).sum().replace(0, np.nan)
        vi_plus    = vm_plus.rolling(period).sum()  / tr_sum
        vi_minus   = vm_minus.rolling(period).sum() / tr_sum
        return vi_plus, vi_minus

    def _supertrend(self, high: pd.Series, low: pd.Series, close: pd.Series,
                    period: int = 10, multiplier: float = 3.0) -> tuple[pd.Series, pd.Series]:
        """Supertrend — ATR-based adaptive trailing stop and direction."""
        h   = high.values.astype(float)
        l   = low.values.astype(float)
        c   = close.values.astype(float)
        n   = len(c)
        atr = self._atr_np(h, l, c, period)

        hl2      = (h + l) / 2.0
        basic_ub = hl2 + multiplier * atr
        basic_lb = hl2 - multiplier * atr

        final_ub  = basic_ub.copy()
        final_lb  = basic_lb.copy()
        st        = np.full(n, np.nan)
        direction = np.ones(n)   # 1=bullish, -1=bearish

        if n > 0:
            st[0] = final_lb[0]

        for i in range(1, n):
            # Upper band — ratchet downward (or reset when price crosses)
            if basic_ub[i] < final_ub[i - 1] or c[i - 1] > final_ub[i - 1]:
                final_ub[i] = basic_ub[i]
            else:
                final_ub[i] = final_ub[i - 1]
            # Lower band — ratchet upward (or reset when price crosses)
            if basic_lb[i] > final_lb[i - 1] or c[i - 1] < final_lb[i - 1]:
                final_lb[i] = basic_lb[i]
            else:
                final_lb[i] = final_lb[i - 1]
            # Direction: compare previous supertrend line
            if np.isnan(st[i - 1]):
                direction[i] = 1.0
            elif st[i - 1] >= final_ub[i - 1]:   # was bearish
                direction[i] = 1.0 if c[i] > final_ub[i] else -1.0
            else:                                  # was bullish
                direction[i] = -1.0 if c[i] < final_lb[i] else 1.0
            st[i] = final_lb[i] if direction[i] == 1.0 else final_ub[i]

        return pd.Series(st, index=close.index), pd.Series(direction, index=close.index)

    def _parabolic_sar(self, high: pd.Series, low: pd.Series, close: pd.Series,
                       af_start: float = 0.02, af_max: float = 0.20) -> tuple[pd.Series, pd.Series]:
        """Parabolic SAR — trailing acceleration-based stop."""
        h = high.values.astype(float)
        l = low.values.astype(float)
        n = len(h)

        psar    = np.full(n, np.nan)
        is_bull = np.ones(n, dtype=bool)
        af      = af_start
        ep      = h[0]        # extreme point (highest when bullish)
        psar[0] = l[0]

        for i in range(1, n):
            prev_bull = is_bull[i - 1]
            prev_psar = psar[i - 1]

            if prev_bull:
                new_sar = prev_psar + af * (ep - prev_psar)
                # SAR must not be above last two lows
                if i >= 2:
                    new_sar = min(new_sar, l[i - 1], l[i - 2])
                else:
                    new_sar = min(new_sar, l[i - 1])

                if l[i] < new_sar:          # reversal to bearish
                    is_bull[i] = False
                    psar[i]    = ep         # SAR jumps to highest point
                    ep         = l[i]       # new EP = current low
                    af         = af_start
                else:
                    is_bull[i] = True
                    psar[i]    = new_sar
                    if h[i] > ep:
                        ep = h[i]
                        af = min(af + af_start, af_max)
            else:
                new_sar = prev_psar + af * (ep - prev_psar)
                # SAR must not be below last two highs
                if i >= 2:
                    new_sar = max(new_sar, h[i - 1], h[i - 2])
                else:
                    new_sar = max(new_sar, h[i - 1])

                if h[i] > new_sar:          # reversal to bullish
                    is_bull[i] = True
                    psar[i]    = ep         # SAR jumps to lowest point
                    ep         = h[i]       # new EP = current high
                    af         = af_start
                else:
                    is_bull[i] = False
                    psar[i]    = new_sar
                    if l[i] < ep:
                        ep = l[i]
                        af = min(af + af_start, af_max)

        return pd.Series(psar, index=close.index), pd.Series(is_bull.astype(float), index=close.index)

    def _mfi(self, high: pd.Series, low: pd.Series, close: pd.Series,
             volume: pd.Series, period: int) -> pd.Series:
        """Money Flow Index (0-100) — volume-weighted RSI."""
        tp      = (high + low + close) / 3.0
        mf      = tp * volume
        tp_diff = tp.diff()
        pos_mf  = mf.where(tp_diff >  0, 0.0)
        neg_mf  = mf.where(tp_diff <= 0, 0.0)
        pos_sum = pos_mf.rolling(period).sum()
        neg_sum = neg_mf.rolling(period).sum()
        mfr     = pos_sum / neg_sum.replace(0, np.nan)
        return 100.0 - (100.0 / (1.0 + mfr))
