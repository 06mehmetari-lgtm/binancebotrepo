"""
ATR-based dynamic stop-loss and take-profit calculator — Phase 2.
Uses ATR% from feature engine to set risk-proportional levels.
Minimum R:R = 3:1 (stop floor 0.8%, TP floor 2.4%).
"""


class ATRStopLoss:
    DEFAULT_STOP_MULT = 1.0   # stop = ATR × 1.0
    DEFAULT_TP_MULT   = 3.0   # TP   = ATR × 3.0  → 3:1 R:R
    MIN_STOP_PCT      = 0.8   # floor: never less than 0.8%
    MIN_TP_PCT        = 2.4   # floor: never less than 2.4% (3:1 × 0.8%)
    MAX_STOP_PCT      = 5.0   # ceiling: never more than 5%
    MIN_ATR_PCT       = 0.3   # treat ATR below this as noise

    def calculate(
        self,
        direction: str,
        atr_pct: float,
        stop_mult: float | None = None,
        tp_mult: float | None = None,
    ) -> dict:
        """
        Returns stop_pct (negative = below entry) and tp_pct (positive = above entry)
        as percentage offsets from entry price. For short: signs are flipped.
        """
        if direction == "flat":
            return {"stop_pct": 0.0, "tp_pct": 0.0, "risk_reward": 0.0, "atr_pct": atr_pct}

        sm = stop_mult or self.DEFAULT_STOP_MULT
        tm = tp_mult or self.DEFAULT_TP_MULT

        atr     = max(atr_pct, self.MIN_ATR_PCT)
        raw_stop = atr * sm
        raw_tp   = atr * tm

        stop = max(self.MIN_STOP_PCT, min(self.MAX_STOP_PCT, raw_stop))
        tp   = max(self.MIN_TP_PCT, raw_tp)

        # Maintain R:R ratio if stop was clipped
        if raw_stop != stop:
            tp = max(self.MIN_TP_PCT, stop * (tm / sm))

        rr = round(tp / stop, 2) if stop > 0 else 3.0

        if direction == "long":
            return {"stop_pct": round(-stop, 3), "tp_pct": round(tp, 3), "risk_reward": rr, "atr_pct": atr_pct}
        else:  # short
            return {"stop_pct": round(stop, 3), "tp_pct": round(-tp, 3), "risk_reward": rr, "atr_pct": atr_pct}

    def regime_multipliers(self, regime: str) -> tuple[float, float]:
        """Maintain 3:1 R:R across regimes; widen in volatile, tighten in ranging."""
        if regime == "volatile":
            return 1.5, 4.5   # wider stops in volatile → 3:1 R:R preserved
        if regime in ("trending_up", "trending_down"):
            return 1.2, 3.6   # trend: slight trail → 3:1 R:R preserved
        if regime == "ranging":
            return 0.8, 2.4   # ranging: tighter → 3:1 R:R preserved
        return self.DEFAULT_STOP_MULT, self.DEFAULT_TP_MULT
