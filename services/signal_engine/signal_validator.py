class SignalValidator:
    def validate(self, signal: dict, context: dict) -> tuple[bool, str]:
        if signal.get("confidence", 0) < 0.52:
            return False, f"confidence {signal['confidence']:.2f} too low"
        if context.get("crisis_level", 0) >= 4:
            return False, "crisis level 4: no trading"
        if context.get("drift_status") == "SHOCK":
            return False, "SHOCK drift: no trading"
        if signal.get("direction") == "flat":
            return False, "flat signal"
        return True, "ok"
