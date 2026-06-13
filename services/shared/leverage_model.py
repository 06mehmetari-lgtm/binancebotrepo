"""
Per-symbol leverage from analysis — ATR, crisis, confidence, regime, drift.
Dashboard coin page uses the same ATR tiers; trading pipeline reads signal.leverage.
"""

from __future__ import annotations

import os


def _parse_dissent(value: float | str | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    if not s:
        return 0.0
    mapping = {"low": 0.15, "medium": 0.4, "high": 0.7, "critical": 0.9}
    if s in mapping:
        return mapping[s]
    try:
        return float(s)
    except ValueError:
        return 0.4 if "high" in s else 0.2


def _atr_base_leverage(atr_pct: float) -> int:
    """atr_pct as decimal (0.01 = 1%). Low vol → higher leverage."""
    if atr_pct < 0.005:
        return 10
    if atr_pct < 0.010:
        return 7
    if atr_pct < 0.015:
        return 5
    if atr_pct < 0.020:
        return 3
    return 2


def _confidence_cap(confidence: float) -> int:
    if confidence < 0.62:
        return 1
    if confidence < 0.70:
        return 5
    if confidence < 0.78:
        return 10
    return int(os.getenv("LEVERAGE_CONF_HIGH_CAP", "20"))


def recommend_leverage(
    *,
    confidence: float,
    crisis_level: int = 0,
    regime: str = "unknown",
    atr_pct: float = 0.0,
    drift_status: str = "STABLE",
    dissent_risk: float | str | None = None,
    global_max: float = 3.0,
    direction: str = "flat",
    is_valid: bool = True,
) -> dict:
    """
    Returns leverage (int 1..global_max), reasons, and diagnostic fields.
    """
    reasons: list[str] = []
    if direction not in ("long", "short") or not is_valid:
        return {
            "leverage": 1,
            "base_lev": 1,
            "crisis_mult": 1.0,
            "confidence_cap": 1,
            "reasons": ["flat_or_invalid"],
        }

    if crisis_level >= 4:
        return {
            "leverage": 1,
            "base_lev": 1,
            "crisis_mult": 0.0,
            "confidence_cap": 1,
            "reasons": ["crisis_4_no_leverage"],
        }

    base = _atr_base_leverage(max(0.0, float(atr_pct)))
    reasons.append(f"atr_base_{base}x")

    crisis_mults = (1.0, 0.75, 0.5, 0.25, 0.0)
    crisis_mult = crisis_mults[min(int(crisis_level), 4)]
    if crisis_level >= 1:
        reasons.append(f"crisis_{crisis_level}_x{crisis_mult}")

    regime_mult = 1.0
    r = str(regime or "unknown").lower()
    if r == "volatile":
        regime_mult = 0.5
        reasons.append("regime_volatile_half")
    elif r == "ranging":
        regime_mult = 0.75
        reasons.append("regime_ranging_reduce")
    elif r in ("trending_up", "trending_down"):
        regime_mult = 1.1
        reasons.append("regime_trend_boost")

    drift_mult = 1.0
    drift = str(drift_status or "STABLE").upper()
    if drift == "SHOCK":
        return {
            "leverage": 1,
            "base_lev": base,
            "crisis_mult": crisis_mult,
            "confidence_cap": 1,
            "reasons": ["drift_shock_1x"],
        }
    if drift == "DRIFTING":
        drift_mult = 0.6
        reasons.append("drift_reduce")
    elif drift == "WARNING":
        drift_mult = 0.8
        reasons.append("drift_warning")

    dissent = _parse_dissent(dissent_risk)
    dissent_mult = 1.0
    if dissent >= 0.5:
        dissent_mult = 0.5
        reasons.append("high_dissent_half")
    elif dissent >= 0.3:
        dissent_mult = 0.7
        reasons.append("dissent_reduce")

    conf_cap = _confidence_cap(float(confidence))
    if conf_cap == 1:
        reasons.append(f"low_conf_{confidence:.0%}_1x")
    elif conf_cap < 20:
        reasons.append(f"conf_cap_{conf_cap}x")

    raw = base * crisis_mult * regime_mult * drift_mult * dissent_mult
    lev = max(1, round(raw))
    lev = min(lev, conf_cap)
    gmax = max(1.0, float(global_max))
    if lev > gmax:
        reasons.append(f"global_cap_{gmax:.0f}x")
    lev = int(min(lev, gmax))

    return {
        "leverage": lev,
        "base_lev": base,
        "crisis_mult": round(crisis_mult, 2),
        "confidence_cap": conf_cap,
        "regime_mult": regime_mult,
        "raw_score": round(raw, 2),
        "reasons": reasons,
    }
