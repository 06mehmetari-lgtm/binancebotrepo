"""Neutral agent — detects ranging/uncertain markets and votes HOLD."""

class NeutralAgent:
    def analyze(self, context: dict) -> dict:
        f = context.get("features", {})
        adx = float(f.get("adx_14", 0))
        bb_squeeze = float(f.get("bb_squeeze", 2))
        crisis_level = int(context.get("crisis_level", 0))

        # Low ADX = no trend, tight BB = compression = uncertain
        if adx < 20 or bb_squeeze < 0.5 or crisis_level >= 3:
            return {"agent": "neutral_agent", "signal": "flat", "confidence": 0.75,
                    "reasoning": {"adx": adx, "bb_squeeze": bb_squeeze, "crisis": crisis_level}}
        return {"agent": "neutral_agent", "signal": "flat", "confidence": 0.25,
                "reasoning": {"adx": adx}}
