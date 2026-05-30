from dataclasses import dataclass
from typing import Literal

Direction = Literal["long", "short", "flat"]

@dataclass
class Signal:
    symbol: str
    direction: Direction
    confidence: float
    kelly_fraction: float
    source: str
    timestamp: int

class SignalGenerator:
    def generate(self, agent_verdicts: list[dict], kelly_fraction: float) -> Signal | None:
        if not agent_verdicts:
            return None
        votes = {"long": 0.0, "short": 0.0, "flat": 0.0}
        for v in agent_verdicts:
            direction = v.get("direction", "flat")
            confidence = float(v.get("confidence", 0.5))
            if direction in votes:
                votes[direction] += confidence
        direction = max(votes, key=votes.__getitem__)
        total = sum(votes.values())
        confidence = votes[direction] / total if total else 0.0
        if confidence < 0.6:
            direction = "flat"
        import time
        return Signal(
            symbol="BTCUSDT",
            direction=direction,
            confidence=confidence,
            kelly_fraction=kelly_fraction,
            source="signal_engine",
            timestamp=int(time.time() * 1000),
        )
