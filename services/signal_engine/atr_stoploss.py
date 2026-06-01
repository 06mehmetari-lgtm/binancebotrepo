"""
ATR-based dynamic stop-loss and take-profit calculator — Phase 2.
Uses ATR% from feature engine to set risk-proportional levels.
Default risk/reward: 1:2 (stop = 1.5× ATR, TP = 3.0× ATR).
"""


class ATRStopLoss:
    DEFAULT_STOP_MULT = 1.5   # stop = ATR × 1.5
    DEFAULT_TP_MULT   = 3.0   # TP   = ATR × 3.0
    MIN_STOP_PCT      = 0.4   # floor: never less than 0.4%
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
        as percentage offsets from entry price.
        For short: signs are flipped.
        """
        if direction == "flat":
            return {"stop_pct": 0.0, "tp_pct": 0.0, "risk_reward": 0.0, "atr_pct": atr_pct}

        sm = stop_mult or self.DEFAULT_STOP_MULT
        tm = tp_mult or self.DEFAULT_TP_MULT

        atr = max(atr_pct, self.MIN_ATR_PCT)
        raw_stop = atr * sm
        raw_tp   = atr * tm

        stop = max(self.MIN_STOP_PCT, min(self.MAX_STOP_PCT, raw_stop))
        tp   = max(self.MIN_STOP_PCT * 2, raw_tp)

        # Adjust TP proportionally if stop was clipped
        if raw_stop != stop:
            tp = stop * (tm / sm)

        rr = round(tp / stop, 2) if stop > 0 else 2.0

        if direction == "long":
            return {"stop_pct": round(-stop, 3), "tp_pct": round(tp, 3), "risk_reward": rr, "atr_pct": atr_pct}
        else:  # short
            return {"stop_pct": round(stop, 3), "tp_pct": round(-tp, 3), "risk_reward": rr, "atr_pct": atr_pct}

    def regime_multipliers(self, regime: str) -> tuple[float, float]:
        """Widen stops in volatile regimes, tighten in ranging."""
        if regime == "volatile":
            return 2.0, 3.5
        if regime == "trending_up" or regime == "trending_down":
            return 1.5, 3.5   # trend: trail further
        if regime == "ranging":
            return 1.0, 2.0   # ranging: tighter, quicker profit
        return self.DEFAULT_STOP_MULT, self.DEFAULT_TP_MULT
