"""
Volume Profile features: VPOC, Value Area, distance from key levels.
Uses last N 1m candles to build a price-volume histogram.
"""
import numpy as np


class VolumeProfileBuilder:
    BUCKETS = 24      # price levels in the histogram
    VALUE_AREA = 0.70  # 70% of volume = value area

    def build(self, ohlcv_history: list, n_candles: int = 200) -> dict:
        features: dict[str, float] = {}
        if len(ohlcv_history) < 30:
            return self._empty()

        candles = ohlcv_history[-n_candles:]
        highs   = [c[1] for c in candles]
        lows    = [c[2] for c in candles]
        closes  = [c[3] for c in candles]
        vols    = [c[4] for c in candles]

        price_range_hi = max(highs)
        price_range_lo = min(lows)
        current_price  = closes[-1]

        if price_range_hi <= price_range_lo or price_range_hi == 0:
            return self._empty()

        bucket_size = (price_range_hi - price_range_lo) / self.BUCKETS
        vol_buckets = np.zeros(self.BUCKETS)

        for i, c in enumerate(candles):
            mid   = (c[1] + c[2]) / 2  # midpoint of candle
            b_idx = int((mid - price_range_lo) / bucket_size)
            b_idx = max(0, min(self.BUCKETS - 1, b_idx))
            vol_buckets[b_idx] += vols[i]

        # VPOC: price level with highest volume
        vpoc_idx   = int(np.argmax(vol_buckets))
        vpoc_price = price_range_lo + (vpoc_idx + 0.5) * bucket_size

        # Value Area: expand from VPOC until 70% of total volume is covered
        total_vol  = vol_buckets.sum()
        va_vol     = vol_buckets[vpoc_idx]
        lo_idx     = vpoc_idx
        hi_idx     = vpoc_idx
        while va_vol < total_vol * self.VALUE_AREA and (lo_idx > 0 or hi_idx < self.BUCKETS - 1):
            lo_candidate = vol_buckets[lo_idx - 1] if lo_idx > 0 else 0
            hi_candidate = vol_buckets[hi_idx + 1] if hi_idx < self.BUCKETS - 1 else 0
            if lo_candidate >= hi_candidate and lo_idx > 0:
                lo_idx -= 1
                va_vol += lo_candidate
            elif hi_idx < self.BUCKETS - 1:
                hi_idx += 1
                va_vol += hi_candidate
            else:
                lo_idx -= 1
                va_vol += lo_candidate

        vah_price = price_range_lo + (hi_idx + 1) * bucket_size
        val_price = price_range_lo + lo_idx * bucket_size

        # Normalized distances (% from current price)
        dist_vpoc = (current_price - vpoc_price) / vpoc_price * 100
        dist_vah  = (current_price - vah_price)  / vah_price  * 100
        dist_val  = (current_price - val_price)   / val_price  * 100

        # Is price inside value area?
        in_va = 1.0 if val_price <= current_price <= vah_price else 0.0

        # Normalized VPOC volume dominance (0-1, higher = stronger VPOC)
        vpoc_dominance = float(vol_buckets[vpoc_idx] / total_vol) if total_vol > 0 else 0.0

        features["vpoc_dist_pct"]    = float(np.clip(dist_vpoc, -10, 10))
        features["vah_dist_pct"]     = float(np.clip(dist_vah, -10, 10))
        features["val_dist_pct"]     = float(np.clip(dist_val, -10, 10))
        features["in_value_area"]    = in_va
        features["vpoc_dominance"]   = float(np.clip(vpoc_dominance, 0, 1))
        # -1 = below VAL (discount), 0 = inside VA, 1 = above VAH (premium)
        if current_price < val_price:
            features["va_position"] = -1.0
        elif current_price > vah_price:
            features["va_position"] = 1.0
        else:
            features["va_position"] = 0.0

        return features

    def _empty(self) -> dict:
        return {
            "vpoc_dist_pct": 0.0, "vah_dist_pct": 0.0, "val_dist_pct": 0.0,
            "in_value_area": 0.0, "vpoc_dominance": 0.0, "va_position": 0.0,
        }
