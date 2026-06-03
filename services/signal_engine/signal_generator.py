import time
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
    def generate(self, symbol: str, agent_verdicts: list[dict],
                 kelly_fraction: float, features: dict | None = None) -> Signal | None:
        """
        Generate signal from agent verdicts.
        Falls back to technical analysis when no verdicts available.
        """
        direction: Direction = "flat"
        confidence = 0.0
        source = "signal_engine"

        if agent_verdicts:
            # ── Agent-based signal ──────────────────────────────────────────
            votes: dict[str, float] = {"long": 0.0, "short": 0.0, "flat": 0.0}
            for v in agent_verdicts:
                d = v.get("direction", "flat")
                c = float(v.get("confidence", 0.5))
                if d in votes:
                    votes[d] += c
            best = max(votes, key=votes.__getitem__)
            total = sum(votes.values())
            confidence = votes[best] / total if total else 0.0
            try:
                from risk_limits import get_active_limits
                min_conf = get_active_limits().min_signal_confidence
            except Exception:
                min_conf = 0.60
            direction = best if confidence >= min_conf else "flat"
            source = "agent_system"

        elif features:
            # ── Technical fallback (no agents / Anthropic key not set) ──────
            rsi = float(features.get("rsi_14", 50) or 50)
            macd_hist = float(features.get("macd_hist", 0) or 0)
            bb_pos = float(features.get("bb_position", 0.5) or 0.5)
            trend = float(features.get("ema_trend", 0) or 0)
            vol_ratio = float(features.get("volume_ratio", 1.0) or 1.0)
            adx = float(features.get("adx_14", 20) or 20)

            # Scoring: accumulate evidence
            long_score = 0.0
            short_score = 0.0

            if rsi < 28:
                long_score += 0.25
            elif rsi < 35:
                long_score += 0.12
            if rsi > 72:
                short_score += 0.25
            elif rsi > 65:
                short_score += 0.12

            if macd_hist > 0:
                long_score += 0.15
            elif macd_hist < 0:
                short_score += 0.15

            if bb_pos < 0.15:
                long_score += 0.15
            elif bb_pos > 0.85:
                short_score += 0.15

            if trend > 0:
                long_score += 0.10
            elif trend < 0:
                short_score += 0.10

            if vol_ratio > 1.5:
                # volume surge amplifies whichever direction is leading
                leading_bonus = 0.08
                if long_score > short_score:
                    long_score += leading_bonus
                elif short_score > long_score:
                    short_score += leading_bonus

            # Require ADX > 20 to confirm trend (avoid choppy signals)
            if adx < 18:
                long_score *= 0.6
                short_score *= 0.6

            try:
                from risk_limits import get_active_limits
                min_conf = get_active_limits().min_signal_confidence
            except Exception:
                min_conf = 0.60
            if long_score >= min_conf and long_score > short_score:
                direction = "long"
                confidence = min(0.95, long_score)
            elif short_score >= min_conf and short_score > long_score:
                direction = "short"
                confidence = min(0.95, short_score)
            else:
                direction = "flat"
                confidence = max(long_score, short_score)

            source = "technical"
        else:
            return None

        return Signal(
            symbol=symbol,
            direction=direction,
            confidence=round(confidence, 4),
            kelly_fraction=kelly_fraction,
            source=source,
            timestamp=int(time.time() * 1000),
        )
