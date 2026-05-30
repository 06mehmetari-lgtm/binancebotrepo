from signal_generator import Signal

class SignalValidator:
    def validate(self, signal: Signal, liquidity_usd: float,
                 portfolio_value: float) -> tuple[bool, str]:
        if signal.confidence < 0.55:
            return False, f"confidence {signal.confidence:.2f} below threshold"
        if liquidity_usd < 1_000_000:
            return False, "insufficient liquidity"
        if signal.kelly_fraction <= 0:
            return False, "negative kelly — no edge"
        return True, "ok"
