import time
from dataclasses import dataclass, field
from typing import Literal

Direction = Literal["long", "short", "flat"]

ML_BOOST      = 0.20   # max confidence boost from ML score agreement (was 0.12)
ML_PENALTY    = 0.15   # confidence penalty when ML disagrees (was 0.08)
ML_THRESHOLD  = 0.15   # |ml_score| must exceed this to influence signal (was 0.25, lowered)


@dataclass
class Signal:
    symbol: str
    direction: Direction
    confidence: float
    kelly_fraction: float
    source: str
    timestamp: int
    ml_score: float = 0.0
    stop_pct: float = 0.0
    tp_pct: float   = 0.0
    risk_reward: float = 0.0


class SignalGenerator:
    def generate(
        self,
        symbol: str,
        agent_verdicts: list[dict],
        kelly_fraction: float,
        features: dict | None = None,
        ml_score: float = 0.0,
        stop_pct: float = 0.0,
        tp_pct: float = 0.0,
        risk_reward: float = 0.0,
    ) -> Signal | None:
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

            # ── ML score modulation ─────────────────────────────────────────
            # ml_score in [-1, +1]: positive = ML expects long, negative = short
            if abs(ml_score) >= ML_THRESHOLD:
                ml_favors_long  = ml_score > 0
                ml_favors_short = ml_score < 0
                if best == "long" and ml_favors_long:
                    confidence = min(0.98, confidence + ML_BOOST * abs(ml_score))
                elif best == "short" and ml_favors_short:
                    confidence = min(0.98, confidence + ML_BOOST * abs(ml_score))
                elif best in ("long", "short") and (
                    (best == "long" and ml_favors_short) or
                    (best == "short" and ml_favors_long)
                ):
                    confidence = max(0.0, confidence - ML_PENALTY * abs(ml_score))

            direction = best if confidence >= 0.52 else "flat"
            source = "agent_system"

        elif features:
            # ── Technical fallback ──────────────────────────────────────────
            rsi       = float(features.get("rsi_14", 50) or 50)
            macd_hist = float(features.get("macd_hist", 0) or 0)
            bb_pos    = float(features.get("bb_position", 0.5) or 0.5)
            trend     = float(features.get("ema_trend", 0) or 0)
            vol_ratio = float(features.get("volume_ratio", 1.0) or 1.0)
            adx       = float(features.get("adx_14", 20) or 20)

            long_score = 0.0
            short_score = 0.0

            if rsi < 28:    long_score  += 0.25
            elif rsi < 35:  long_score  += 0.12
            if rsi > 72:    short_score += 0.25
            elif rsi > 65:  short_score += 0.12

            if macd_hist > 0:   long_score  += 0.15
            elif macd_hist < 0: short_score += 0.15

            if bb_pos < 0.15:   long_score  += 0.15
            elif bb_pos > 0.85: short_score += 0.15

            if trend > 0:   long_score  += 0.10
            elif trend < 0: short_score += 0.10

            if vol_ratio > 1.5:
                if long_score > short_score:    long_score  += 0.08
                elif short_score > long_score:  short_score += 0.08

            if adx < 18:
                long_score  *= 0.6
                short_score *= 0.6

            # Apply ML score to technical fallback too
            if abs(ml_score) >= ML_THRESHOLD:
                if ml_score > 0:    long_score  += ML_BOOST * ml_score
                else:               short_score += ML_BOOST * abs(ml_score)

            if long_score >= 0.55 and long_score > short_score:
                direction = "long"
                confidence = min(0.95, long_score)
            elif short_score >= 0.55 and short_score > long_score:
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
            ml_score=round(ml_score, 4),
            stop_pct=stop_pct,
            tp_pct=tp_pct,
            risk_reward=risk_reward,
        )
