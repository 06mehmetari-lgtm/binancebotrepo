"""
Multi-Timeframe (MTF) Feature Builder

Üç zaman dilimi analizi:
  1H  — kısa vadeli momentum + trend
  4H  — orta vadeli trend + Ichimoku + ADX
  1D  — uzun vadeli trend, günlük aralık pozisyonu

Confluence (uyum) skoru: 3 zaman diliminin aynı yönde fikir birliği.
"""
import json
import numpy as np
import pandas as pd


class MTFFeatureBuilder:
    def build(
        self,
        klines_1h_raw: str | None,
        klines_4h_raw: str | None,
        klines_1d_raw: str | None,
        current_features: dict,
    ) -> dict:
        feats_1h = self._build_1h(klines_1h_raw)
        feats_4h = self._build_4h(klines_4h_raw)
        feats_1d = self._build_1d(klines_1d_raw)
        confluence = self._confluence(current_features, feats_1h, feats_4h, feats_1d)
        return {**feats_1h, **feats_4h, **feats_1d, **confluence}

    # ──────────────────────────── 1H ─────────────────────────────────────────

    def _build_1h(self, raw: str | None) -> dict:
        if not raw:
            return self._empty_1h()
        try:
            klines = json.loads(raw)
        except Exception:
            return self._empty_1h()
        if len(klines) < 26:
            return self._empty_1h()

        c = np.array([float(k["close"])  for k in klines], dtype=np.float64)
        h = np.array([float(k["high"])   for k in klines], dtype=np.float64)
        l = np.array([float(k["low"])    for k in klines], dtype=np.float64)
        v = np.array([float(k["volume"]) for k in klines], dtype=np.float64)

        feats: dict[str, float] = {}
        feats["rsi_14_1h"]   = float(self._rsi(c, 14))
        feats["macd_hist_1h"] = float(np.clip(self._macd_hist(c, c[-1]), -5, 5))

        s = pd.Series(c)
        ema20 = float(s.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(s.ewm(span=50, adjust=False).mean().iloc[-1]) if len(c) >= 50 else ema20
        feats["trend_1h"]     = float(np.clip((ema20 - ema50) / max(ema50, 1) * 100, -5, 5))
        feats["atr_pct_1h"]   = float(np.clip(self._atr(h, l, c, 14) / max(c[-1], 1) * 100, 0, 20))
        feats["adx_1h"]       = float(np.clip(self._adx(h, l, c, 14), 0, 100))

        vol_ma = np.mean(v[-20:]) if len(v) >= 20 else v.mean()
        feats["vol_trend_1h"] = float(np.clip(v[-1] / max(vol_ma, 1) - 1, -2, 2))

        # Ichimoku cloud position on 1H
        ichi_sig = self._ichimoku_signal(h, l, c)
        feats["ichi_signal_1h"]   = float(ichi_sig)          # +1/0/-1

        feats["ob_1h"] = 1.0 if feats["rsi_14_1h"] > 70 else 0.0
        feats["os_1h"] = 1.0 if feats["rsi_14_1h"] < 30 else 0.0
        return feats

    # ──────────────────────────── 4H ─────────────────────────────────────────

    def _build_4h(self, raw: str | None) -> dict:
        if not raw:
            return self._empty_4h()
        try:
            klines = json.loads(raw)
        except Exception:
            return self._empty_4h()
        if len(klines) < 26:
            return self._empty_4h()

        c = np.array([float(k["close"])  for k in klines], dtype=np.float64)
        h = np.array([float(k["high"])   for k in klines], dtype=np.float64)
        l = np.array([float(k["low"])    for k in klines], dtype=np.float64)

        feats: dict[str, float] = {}
        feats["rsi_14_4h"]     = float(self._rsi(c, 14))
        feats["macd_hist_4h"]  = float(np.clip(self._macd_hist(c, c[-1]), -5, 5))
        feats["adx_4h"]        = float(np.clip(self._adx(h, l, c, 14), 0, 100))
        feats["atr_pct_4h"]    = float(np.clip(self._atr(h, l, c, 14) / max(c[-1], 1) * 100, 0, 20))

        s = pd.Series(c)
        ema20 = float(s.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(s.ewm(span=50, adjust=False).mean().iloc[-1]) if len(c) >= 50 else ema20
        ema200= float(s.ewm(span=200,adjust=False).mean().iloc[-1]) if len(c) >= 200 else ema50
        feats["trend_4h"]       = float(np.clip((ema20 - ema50)  / max(ema50, 1)  * 100, -10, 10))
        feats["major_trend_4h"] = float(np.clip((ema50 - ema200) / max(ema200, 1) * 100, -10, 10))
        feats["price_vs_ema200_4h"] = float(np.clip((c[-1] - ema200) / max(ema200, 1) * 100, -10, 10))

        # Aroon (25) on 4H
        if len(c) >= 26:
            feats["aroon_osc_4h"] = float(self._aroon_osc(h, l, 25))
        else:
            feats["aroon_osc_4h"] = 0.0

        # Ichimoku on 4H
        feats["ichi_signal_4h"] = float(self._ichimoku_signal(h, l, c))

        feats["ob_4h"] = 1.0 if feats["rsi_14_4h"] > 70 else 0.0
        feats["os_4h"] = 1.0 if feats["rsi_14_4h"] < 30 else 0.0
        return feats

    # ──────────────────────────── 1D ─────────────────────────────────────────

    def _build_1d(self, raw: str | None) -> dict:
        if not raw:
            return self._empty_1d()
        try:
            klines = json.loads(raw)
        except Exception:
            return self._empty_1d()
        if len(klines) < 14:
            return self._empty_1d()

        c = np.array([float(k["close"])  for k in klines], dtype=np.float64)
        h = np.array([float(k["high"])   for k in klines], dtype=np.float64)
        l = np.array([float(k["low"])    for k in klines], dtype=np.float64)
        v = np.array([float(k["volume"]) for k in klines], dtype=np.float64)

        feats: dict[str, float] = {}
        feats["rsi_14_1d"]    = float(self._rsi(c, 14))
        feats["adx_1d"]       = float(np.clip(self._adx(h, l, c, 14), 0, 100))
        feats["atr_pct_1d"]   = float(np.clip(self._atr(h, l, c, 14) / max(c[-1], 1) * 100, 0, 20))

        s = pd.Series(c)
        ema20  = float(s.ewm(span=20,  adjust=False).mean().iloc[-1])
        ema200 = float(s.ewm(span=200, adjust=False).mean().iloc[-1]) if len(c) >= 200 else ema20
        feats["trend_1d"]          = float(np.clip((c[-1] - ema20)  / max(ema20, 1)  * 100, -20, 20))
        feats["major_trend_1d"]    = float(np.clip((ema20 - ema200) / max(ema200, 1) * 100, -20, 20))
        feats["price_vs_ema200_1d"]= float(np.clip((c[-1] - ema200) / max(ema200, 1) * 100, -20, 20))

        # 20-day range position (donchian on daily)
        if len(c) >= 20:
            hi20 = h[-20:].max()
            lo20 = l[-20:].min()
            rng  = max(hi20 - lo20, 1e-8)
            feats["daily_range_pos"] = float((c[-1] - lo20) / rng)  # 0=bottom, 1=top
        else:
            feats["daily_range_pos"] = 0.5

        # Daily volume trend
        if len(v) >= 10:
            vol_ma10 = np.mean(v[-10:])
            feats["vol_trend_1d"] = float(np.clip(v[-1] / max(vol_ma10, 1) - 1, -2, 2))
        else:
            feats["vol_trend_1d"] = 0.0

        feats["ob_1d"] = 1.0 if feats["rsi_14_1d"] > 70 else 0.0
        feats["os_1d"] = 1.0 if feats["rsi_14_1d"] < 30 else 0.0
        return feats

    # ──────────────────────────── Confluence ─────────────────────────────────

    def _confluence(self, cur: dict, f1h: dict, f4h: dict, f1d: dict) -> dict:
        """
        3 zaman diliminin uyumunu ölçer.
        bull_confluence_3tf: 0-3 (kaç zaman dilimi boğa)
        bear_confluence_3tf: 0-3 (kaç zaman dilimi ayı)
        trend_alignment    : -1.0 (tam ayı) → +1.0 (tam boğa)
        """
        rsi_1m = float(cur.get("rsi_14", 50))
        mac_1m = float(cur.get("macd_hist", 0))

        # 1m sinyali
        bull_1m = 1 if (rsi_1m < 50 and mac_1m > 0) else 0
        bear_1m = 1 if (rsi_1m > 50 and mac_1m < 0) else 0

        # 1h sinyali
        rsi_1h = f1h.get("rsi_14_1h", 50)
        mac_1h = f1h.get("macd_hist_1h", 0)
        tr_1h  = f1h.get("trend_1h", 0)
        bull_1h = 1 if (rsi_1h < 50 and mac_1h > 0 and tr_1h > 0) else 0
        bear_1h = 1 if (rsi_1h > 50 and mac_1h < 0 and tr_1h < 0) else 0

        # 4h sinyali
        rsi_4h = f4h.get("rsi_14_4h", 50)
        tr_4h  = f4h.get("trend_4h", 0)
        bull_4h = 1 if (rsi_4h < 55 and tr_4h > 0) else 0
        bear_4h = 1 if (rsi_4h > 45 and tr_4h < 0) else 0

        # 1d sinyali
        rsi_1d = f1d.get("rsi_14_1d", 50)
        tr_1d  = f1d.get("major_trend_1d", 0)
        bull_1d = 1 if (rsi_1d < 60 and tr_1d > 0) else 0
        bear_1d = 1 if (rsi_1d > 40 and tr_1d < 0) else 0

        bull_total = bull_1m + bull_1h + bull_4h + bull_1d
        bear_total = bear_1m + bear_1h + bear_4h + bear_1d
        trend_score = (bull_total - bear_total) / 4.0   # -1.0 to +1.0

        # Legacy keys (geriye uyumluluk)
        bull_conf_legacy = float(bull_1m + bull_1h)
        bear_conf_legacy = float(bear_1m + bear_1h)

        return {
            "bull_confluence":     bull_conf_legacy,
            "bear_confluence":     bear_conf_legacy,
            "trend_alignment":     float((bull_1m + bull_1h - bear_1m - bear_1h) / 2.0),
            "ob_1h":               f1h.get("ob_1h", 0.0),
            "os_1h":               f1h.get("os_1h", 0.0),
            # 3-timeframe confluence (yeni)
            "bull_confluence_3tf": float(bull_total),
            "bear_confluence_3tf": float(bear_total),
            "trend_alignment_3tf": float(trend_score),
            # Özel: major trend agreement (4H + Daily birlikte)
            "major_bull_align":    float(bull_4h + bull_1d),
            "major_bear_align":    float(bear_4h + bear_1d),
        }

    # ──────────────────────────── Hesaplama yardımcıları ─────────────────────

    def _rsi(self, c: np.ndarray, period: int) -> float:
        if len(c) < period + 1:
            return 50.0
        d   = np.diff(c)
        g   = np.where(d > 0, d, 0.0)
        l   = np.where(d < 0, -d, 0.0)
        avg_g = np.mean(g[-period:])
        avg_l = np.mean(l[-period:])
        if avg_l == 0:
            return 100.0
        return float(100.0 - 100.0 / (1.0 + avg_g / avg_l))

    def _macd_hist(self, c: np.ndarray, price: float) -> float:
        s       = pd.Series(c)
        ml      = s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean()
        sig     = ml.ewm(span=9, adjust=False).mean()
        hist    = float((ml - sig).iloc[-1])
        return hist / max(price, 1) * 100.0

    def _atr(self, h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int) -> float:
        if len(c) < 2:
            return 0.0
        hl  = h[1:] - l[1:]
        hc  = np.abs(h[1:] - c[:-1])
        lc  = np.abs(l[1:] - c[:-1])
        tr  = np.maximum(hl, np.maximum(hc, lc))
        return float(np.mean(tr[-period:]))

    def _adx(self, h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int) -> float:
        if len(c) < period + 2:
            return 0.0
        ph = np.diff(h)
        pl = -np.diff(l)
        plus_dm  = np.where((ph > pl) & (ph > 0), ph, 0.0)
        minus_dm = np.where((pl > ph) & (pl > 0), pl, 0.0)
        hl  = h[1:] - l[1:]
        hc  = np.abs(h[1:] - c[:-1])
        lc  = np.abs(l[1:] - c[:-1])
        tr  = np.maximum(hl, np.maximum(hc, lc))
        atr = np.mean(tr[-period:])
        if atr == 0:
            return 0.0
        pdi = 100 * np.mean(plus_dm[-period:])  / atr
        mdi = 100 * np.mean(minus_dm[-period:]) / atr
        denom = pdi + mdi
        if denom == 0:
            return 0.0
        dx  = 100 * abs(pdi - mdi) / denom
        return float(dx)  # simplified (non-smoothed, close enough for confluence)

    def _aroon_osc(self, h: np.ndarray, l: np.ndarray, period: int) -> float:
        if len(h) < period + 1:
            return 0.0
        window_h = h[-(period + 1):]
        window_l = l[-(period + 1):]
        aroon_up   = (float(np.argmax(window_h)) / period) * 100.0
        aroon_down = (float(np.argmin(window_l)) / period) * 100.0
        return float(np.clip(aroon_up - aroon_down, -100, 100))

    def _ichimoku_signal(self, h: np.ndarray, l: np.ndarray, c: np.ndarray) -> float:
        """
        -1 = fiyat bulutun altında (ayı)
         0 = fiyat bulutun içinde (nötr)
        +1 = fiyat bulutun üstünde (boğa)
        """
        if len(c) < 52:
            return 0.0
        tenkan = (h[-9:].max()  + l[-9:].min())  / 2.0
        kijun  = (h[-26:].max() + l[-26:].min()) / 2.0
        # Senkou A ve B 26 bar önceki değerleri (mevcut cloud)
        h26 = h[-52:-26]; l26 = l[-52:-26]
        tenkan_26 = (h[-35:-26].max() + l[-35:-26].min()) / 2.0 if len(h) >= 35 else tenkan
        kijun_26  = (h26.max() + l26.min()) / 2.0
        senkou_a  = (tenkan_26 + kijun_26) / 2.0
        senkou_b  = (h26.max() + l26.min()) / 2.0
        cloud_top = max(senkou_a, senkou_b)
        cloud_bot = min(senkou_a, senkou_b)
        price     = c[-1]
        if price > cloud_top:
            return 1.0
        if price < cloud_bot:
            return -1.0
        return 0.0

    # ──────────────────────────── Empty defaults ─────────────────────────────

    def _empty_1h(self) -> dict:
        return {
            "rsi_14_1h": 50.0, "macd_hist_1h": 0.0, "trend_1h": 0.0,
            "atr_pct_1h": 2.0, "adx_1h": 20.0, "vol_trend_1h": 0.0,
            "ichi_signal_1h": 0.0, "ob_1h": 0.0, "os_1h": 0.0,
        }

    def _empty_4h(self) -> dict:
        return {
            "rsi_14_4h": 50.0, "macd_hist_4h": 0.0, "trend_4h": 0.0,
            "major_trend_4h": 0.0, "price_vs_ema200_4h": 0.0,
            "atr_pct_4h": 2.0, "adx_4h": 20.0, "aroon_osc_4h": 0.0,
            "ichi_signal_4h": 0.0, "ob_4h": 0.0, "os_4h": 0.0,
        }

    def _empty_1d(self) -> dict:
        return {
            "rsi_14_1d": 50.0, "adx_1d": 20.0, "atr_pct_1d": 2.0,
            "trend_1d": 0.0, "major_trend_1d": 0.0, "price_vs_ema200_1d": 0.0,
            "daily_range_pos": 0.5, "vol_trend_1d": 0.0,
            "ob_1d": 0.0, "os_1d": 0.0,
        }
