"""
Smart Money Concepts (SMC) Feature Builder

Hesaplanan özellikler (tümü ML modellerine sayısal input olarak verilir):

  Yapısal analiz   : struct_bullish, struct_bearish (HH+HL / LH+LL)
  Kırılım sinyali  : bos_bullish, bos_bearish (Break of Structure)
  Karakter değişimi: choch_bullish, choch_bearish (Change of Character)
  Swing mesafeleri : dist_to_swing_high, dist_to_swing_low (ATR cinsinden)
  Order Block      : ob_bull_dist, ob_bear_dist, price_in_bull_ob, price_in_bear_ob
  Fair Value Gap   : bull_fvg_dist, bear_fvg_dist (ATR cinsinden)
  Destek/Direnç    : dist_to_resistance, dist_to_support, sr_range_norm

Tüm mesafeler ATR cinsinden ifade edilir (normalize edilmiş, ölçekten bağımsız).
"""
import numpy as np


class SMCFeatureBuilder:
    PIVOT_N = 5      # swing high/low için her iki yönde kaç mum bakılacak
    LOOKBACK = 100   # kaç mum geriye analiz yapılacak
    OB_LOOKBACK = 30 # order block için kaç mum geriye bakılacak
    FVG_LOOKBACK = 30

    def build(self, ohlcv_history: list[list], atr: float) -> dict:
        """
        ohlcv_history : [[open, high, low, close, volume], ...] — en eski en başta
        atr           : mevcut ATR değeri (price_features'dan)
        """
        if len(ohlcv_history) < 50:
            return self._empty()

        data = ohlcv_history[-self.LOOKBACK:]
        opens  = np.array([c[0] for c in data], dtype=np.float64)
        highs  = np.array([c[1] for c in data], dtype=np.float64)
        lows   = np.array([c[2] for c in data], dtype=np.float64)
        closes = np.array([c[3] for c in data], dtype=np.float64)

        n         = len(closes)
        atr_safe  = max(float(atr), 1e-8)
        close_now = closes[-1]

        features: dict[str, float] = {}

        # ── 1. Swing High / Low tespiti ─────────────────────────────────────
        pn = self.PIVOT_N
        sh_idx: list[int] = []   # swing high indeksleri
        sl_idx: list[int] = []   # swing low  indeksleri

        for i in range(pn, n - pn):
            window_h = highs[i - pn: i + pn + 1]
            window_l = lows[i  - pn: i + pn + 1]
            if highs[i] == window_h.max():
                sh_idx.append(i)
            if lows[i] == window_l.min():
                sl_idx.append(i)

        # ── 2. Market Structure (HH/HL vs LH/LL) ───────────────────────────
        if len(sh_idx) >= 2 and len(sl_idx) >= 2:
            sh_vals = highs[[sh_idx[-2], sh_idx[-1]]]   # son 2 swing high değeri
            sl_vals = lows[[sl_idx[-2], sl_idx[-1]]]     # son 2 swing low  değeri

            is_hh = bool(sh_vals[1] > sh_vals[0])  # Higher High
            is_hl = bool(sl_vals[1] > sl_vals[0])  # Higher Low
            is_lh = not is_hh                       # Lower  High
            is_ll = not is_hl                       # Lower  Low

            features["struct_bullish"] = 1.0 if (is_hh and is_hl) else 0.0
            features["struct_bearish"] = 1.0 if (is_lh and is_ll) else 0.0

            last_sh = sh_vals[1]
            last_sl = sl_vals[1]

            # Break of Structure (BOS) — trend devamlılığı
            features["bos_bullish"] = 1.0 if (is_hh and close_now > last_sh) else 0.0
            features["bos_bearish"] = 1.0 if (is_ll and close_now < last_sl) else 0.0

            # Change of Character (CHoCH) — trend dönüşü (gövde kapanışı gerekir)
            features["choch_bullish"] = 1.0 if (is_lh and is_ll and close_now > last_sh) else 0.0
            features["choch_bearish"] = 1.0 if (is_hh and is_hl and close_now < last_sl) else 0.0

            # Swing seviyelerine mesafe (ATR cinsinden)
            nearest_sh_above = min(
                (highs[i] for i in sh_idx if highs[i] > close_now),
                default=close_now + 10 * atr_safe
            )
            nearest_sl_below = max(
                (lows[i] for i in sl_idx if lows[i] < close_now),
                default=close_now - 10 * atr_safe
            )
            features["dist_to_swing_high"] = float(np.clip((nearest_sh_above - close_now) / atr_safe, 0, 10))
            features["dist_to_swing_low"]  = float(np.clip((close_now - nearest_sl_below) / atr_safe, 0, 10))
        else:
            features.update({
                "struct_bullish": 0.0, "struct_bearish": 0.0,
                "bos_bullish": 0.0,    "bos_bearish": 0.0,
                "choch_bullish": 0.0,  "choch_bearish": 0.0,
                "dist_to_swing_high": 5.0, "dist_to_swing_low": 5.0,
            })

        # ── 3. Order Block tespiti ──────────────────────────────────────────
        # Bullish OB: güçlü yukarı hareketten önceki son bearish mum
        # Bearish OB: güçlü aşağı hareketten önceki son bullish mum
        ob_threshold = 1.5 * atr_safe
        ob_start     = max(1, n - self.OB_LOOKBACK)

        bull_ob: tuple[float, float] | None = None   # (low, high)
        bear_ob: tuple[float, float] | None = None

        for i in range(n - 2, ob_start - 1, -1):
            if i + 1 >= n:
                continue
            body_size    = abs(closes[i] - opens[i])
            next_up_move = closes[i + 1] - opens[i + 1]
            next_dn_move = opens[i + 1] - closes[i + 1]

            if bull_ob is None and closes[i] < opens[i] and next_up_move > ob_threshold:
                bull_ob = (lows[i], highs[i])

            if bear_ob is None and closes[i] > opens[i] and next_dn_move > ob_threshold:
                bear_ob = (lows[i], highs[i])

            if bull_ob is not None and bear_ob is not None:
                break

        if bull_ob:
            ob_mid = (bull_ob[0] + bull_ob[1]) / 2.0
            features["ob_bull_dist"]     = float(np.clip((close_now - ob_mid) / atr_safe, -10, 10))
            features["price_in_bull_ob"] = 1.0 if (bull_ob[0] <= close_now <= bull_ob[1]) else 0.0
        else:
            features["ob_bull_dist"]     = 0.0
            features["price_in_bull_ob"] = 0.0

        if bear_ob:
            ob_mid = (bear_ob[0] + bear_ob[1]) / 2.0
            features["ob_bear_dist"]     = float(np.clip((ob_mid - close_now) / atr_safe, -10, 10))
            features["price_in_bear_ob"] = 1.0 if (bear_ob[0] <= close_now <= bear_ob[1]) else 0.0
        else:
            features["ob_bear_dist"]     = 0.0
            features["price_in_bear_ob"] = 0.0

        # ── 4. Fair Value Gap (FVG) tespiti ────────────────────────────────
        # Bullish FVG: mum[i].low > mum[i-2].high (yukarı boşluk)
        # Bearish FVG: mum[i].high < mum[i-2].low (aşağı boşluk)
        bull_fvg_dist = 0.0
        bear_fvg_dist = 0.0

        for i in range(n - 1, max(2, n - self.FVG_LOOKBACK), -1):
            # Bullish FVG
            if lows[i] > highs[i - 2]:
                if close_now < lows[i]:   # boşluk henüz dolmamış
                    bull_fvg_dist = float(np.clip((lows[i] - close_now) / atr_safe, 0, 10))
                    break
            # Bearish FVG
            if highs[i] < lows[i - 2]:
                if close_now > highs[i]:  # boşluk henüz dolmamış
                    bear_fvg_dist = float(np.clip((close_now - highs[i]) / atr_safe, 0, 10))
                    break

        features["bull_fvg_dist"] = bull_fvg_dist
        features["bear_fvg_dist"] = bear_fvg_dist

        # ── 5. Destek / Direnç seviyeleri ──────────────────────────────────
        all_levels: list[float] = []
        for i in sh_idx[-6:]:
            all_levels.append(float(highs[i]))
        for i in sl_idx[-6:]:
            all_levels.append(float(lows[i]))

        if all_levels:
            above = [lv for lv in all_levels if lv > close_now]
            below = [lv for lv in all_levels if lv <= close_now]

            nearest_res = min(above) if above else close_now + 10 * atr_safe
            nearest_sup = max(below) if below else close_now - 10 * atr_safe

            features["dist_to_resistance"] = float(np.clip((nearest_res - close_now) / atr_safe, 0, 10))
            features["dist_to_support"]    = float(np.clip((close_now - nearest_sup) / atr_safe, 0, 10))
            features["sr_range_norm"]      = float(np.clip((nearest_res - nearest_sup) / atr_safe, 0, 20))
        else:
            features["dist_to_resistance"] = 5.0
            features["dist_to_support"]    = 5.0
            features["sr_range_norm"]      = 10.0

        return features

    def _empty(self) -> dict:
        return {
            "struct_bullish": 0.0, "struct_bearish": 0.0,
            "bos_bullish": 0.0,    "bos_bearish": 0.0,
            "choch_bullish": 0.0,  "choch_bearish": 0.0,
            "dist_to_swing_high": 5.0, "dist_to_swing_low": 5.0,
            "ob_bull_dist": 0.0,   "price_in_bull_ob": 0.0,
            "ob_bear_dist": 0.0,   "price_in_bear_ob": 0.0,
            "bull_fvg_dist": 0.0,  "bear_fvg_dist": 0.0,
            "dist_to_resistance": 5.0, "dist_to_support": 5.0,
            "sr_range_norm": 10.0,
        }
