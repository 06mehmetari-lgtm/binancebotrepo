class SignalValidator:
    def _min_confidence(self) -> float:
        try:
            from risk_limits import get_active_limits
            return get_active_limits().min_immunity_confidence
        except Exception:
            return 0.52

    def validate(self, signal: dict, context: dict) -> tuple[bool, str]:
        min_conf = self._min_confidence()
        if signal.get("confidence", 0) < min_conf:
            return False, (
                f"confidence {signal['confidence']:.2f} below minimum {min_conf:.2f}"
            )
        if context.get("crisis_level", 0) >= 4:
            return False, "crisis level 4: no trading"
        if context.get("drift_status") == "SHOCK":
            return False, "SHOCK drift: no trading"
        if signal.get("direction") == "flat":
            return False, "flat signal"
        return True, "ok"
