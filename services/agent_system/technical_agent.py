"""Technical analysis agent — rule-based signal from price indicators."""

class TechnicalAgent:
    def analyze(self, context: dict) -> dict:
        f = context.get("features", {})
        rsi = float(f.get("rsi_14", 50))
        macd_hist = float(f.get("macd_hist", 0))
        adx = float(f.get("adx_14", 0))
        bb_pos = float(f.get("bb_position", 0.5))
        stoch_k = float(f.get("stoch_k", 50))
        mom_5 = float(f.get("mom_5", 0))

        score = 0.0
        score += (50 - rsi) / 50                   # RSI mean reversion
        score += macd_hist * 5                       # MACD direction
        score += (0.5 - bb_pos) * 0.5              # BB position
        score += (50 - stoch_k) / 100               # Stochastic
        score += mom_5 / 10                          # Momentum
        if adx > 25:                                 # Strong trend — amplify
            score *= 1.2

        confidence = min(abs(score), 1.0)
        signal = "long" if score > 0.2 else ("short" if score < -0.2 else "flat")
        return {"agent": "technical_agent", "signal": signal, "confidence": confidence,
                "reasoning": {"rsi": rsi, "macd": macd_hist, "adx": adx}}
