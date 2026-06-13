import os


class SignalValidator:
    def _min_confidence(self) -> float:
        try:
            from risk_limits import get_active_limits, is_paper_unlimited
            from profit_rules import PAPER_MIN_SIGNAL_CONFIDENCE
            lim = get_active_limits()
            if is_paper_unlimited():
                return max(PAPER_MIN_SIGNAL_CONFIDENCE, lim.min_signal_confidence)
            return lim.min_immunity_confidence
        except ImportError:
            try:
                from risk_limits import get_active_limits, is_paper_unlimited
                lim = get_active_limits()
                if is_paper_unlimited():
                    return max(0.58, lim.min_signal_confidence)
                return lim.min_immunity_confidence
            except Exception:
                return 0.52
        except Exception:
            return 0.58

    def _paper_mode(self) -> bool:
        try:
            from risk_limits import is_paper_unlimited
            return is_paper_unlimited()
        except Exception:
            return os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")

    def validate(self, signal: dict, context: dict, verdict: dict | None = None) -> tuple[bool, str]:
        paper = self._paper_mode()
        min_conf = self._min_confidence()
        conf = float(signal.get("confidence", 0) or 0)
        try:
            from profit_rules import conf_meets, is_blacklisted
            if is_blacklisted(str(signal.get("symbol", ""))):
                return False, "symbol blacklisted (churn/low quality)"
            if not conf_meets(conf, min_conf):
                return False, (
                    f"confidence {conf:.2f} below minimum {min_conf:.2f}"
                )
        except ImportError:
            if conf < min_conf:
                return False, (
                    f"confidence {conf:.2f} below minimum {min_conf:.2f}"
                )
        if not paper and context.get("crisis_level", 0) >= 4:
            return False, "crisis level 4: no trading"
        if not paper and context.get("drift_status") == "SHOCK":
            return False, "SHOCK drift: no trading"
        if signal.get("direction") == "flat":
            return False, "flat signal"

        if verdict is not None:
            try:
                from profit_rules import agent_entry_ok
                direction = str(signal.get("direction", "flat"))
                conf = float(signal.get("confidence", 0) or 0)
                ok, why = agent_entry_ok(direction, verdict, conf)
                if not ok:
                    return False, f"agent_gate:{why}"
            except ImportError:
                pass

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
