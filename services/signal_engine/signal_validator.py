import os


class SignalValidator:
    def _min_confidence(self) -> float:
        try:
            from risk_limits import get_active_limits, is_paper_unlimited
            lim = get_active_limits()
            if is_paper_unlimited():
                return min(lim.min_signal_confidence, 0.30)
            return lim.min_immunity_confidence
        except Exception:
            return 0.52

    def _paper_mode(self) -> bool:
        try:
            from risk_limits import is_paper_unlimited
            return is_paper_unlimited()
        except Exception:
            return os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")

    def validate(self, signal: dict, context: dict) -> tuple[bool, str]:
        paper = self._paper_mode()
        min_conf = self._min_confidence()
        if signal.get("confidence", 0) < min_conf:
            return False, (
                f"confidence {signal['confidence']:.2f} below minimum {min_conf:.2f}"
            )
        if not paper and context.get("crisis_level", 0) >= 4:
            return False, "crisis level 4: no trading"
        if not paper and context.get("drift_status") == "SHOCK":
            return False, "SHOCK drift: no trading"
        if signal.get("direction") == "flat":
            return False, "flat signal"

        regime = str(context.get("regime") or signal.get("regime") or "")
        if regime == "manipulation" and not paper:
            return False, "manipulation regime — no entry"

        atr_pct = float(signal.get("atr_pct") or 0)
        if atr_pct <= 0:
            atr_pct = float(context.get("atr_pct") or 0)
        max_atr = float(os.getenv("RISK_MAX_ATR_PCT", "5.0"))
        if atr_pct > max_atr and not paper:
            return False, f"ATR {atr_pct:.1f}% too high"

        return True, "ok"
