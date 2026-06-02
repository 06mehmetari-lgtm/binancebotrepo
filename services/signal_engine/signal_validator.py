class SignalValidator:
    MIN_CONFIDENCE  = 0.70
    MIN_RISK_REWARD = 3.0
    MIN_TP_PCT      = 1.5   # %
    MAX_CONSEC_LOSS = 3     # block coin after this many consecutive losses

    def validate(self, signal: dict, context: dict) -> tuple[bool, str]:
        conf = signal.get("confidence", 0)
        if conf < self.MIN_CONFIDENCE:
            return False, f"confidence {conf:.2f} < {self.MIN_CONFIDENCE}"
        if context.get("crisis_level", 0) >= 4:
            return False, "crisis level 4: no trading"
        if context.get("drift_status") == "SHOCK":
            return False, "SHOCK drift: no trading"
        if signal.get("direction") == "flat":
            return False, "flat signal"
        rr = float(signal.get("risk_reward") or 0)
        if rr > 0 and rr < self.MIN_RISK_REWARD:
            return False, f"risk_reward {rr:.2f} < {self.MIN_RISK_REWARD}"
        tp = abs(float(signal.get("tp_pct") or 0))
        if tp > 0 and tp < self.MIN_TP_PCT:
            return False, f"tp_pct {tp:.2f}% < {self.MIN_TP_PCT}%"
        consec = int(signal.get("consecutive_losses") or 0)
        if consec >= self.MAX_CONSEC_LOSS:
            return False, f"coin blocked: {consec} consecutive losses"
        return True, "ok"
