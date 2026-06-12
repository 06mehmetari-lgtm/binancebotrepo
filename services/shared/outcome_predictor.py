"""Outcome prediction from learning profiles + features — no NN, statistical edge."""

from __future__ import annotations

import json


def predict_outcome(
    direction: str,
    learn_raw: str | None,
    features: dict | None,
    context: dict | None,
) -> dict:
    """
    Returns win_probability, expected_return_pct, max_drawdown_risk, veto, reason.
    Used by signal_engine to scale confidence — never bypasses immunity.
    """
    ctx = context or {}
    feat = features or {}
    base_wr = 0.50
    reasons: list[str] = []

    if learn_raw:
        try:
            profile = json.loads(learn_raw)
        except json.JSONDecodeError:
            profile = {}
        drivers = profile.get("drivers") or []
        stage = str(profile.get("learning_stage", "L0"))
        for d in drivers[:3]:
            effect = d.get("effect", "")
            wr = float(d.get("win_rate", 0) or 0)
            if wr < 0.52 or d.get("samples", 0) < 5:
                continue
            aligned = (
                (direction == "long" and effect in ("long_edge", "up"))
                or (direction == "short" and effect in ("short_edge", "down"))
            )
            opposed = (
                (direction == "long" and effect in ("short_edge", "down"))
                or (direction == "short" and effect in ("long_edge", "up"))
            )
            if aligned:
                base_wr = max(base_wr, wr)
                reasons.append(f"+{d.get('factor', '')}")
            elif opposed:
                base_wr = min(base_wr, 1.0 - wr)
                reasons.append(f"-{d.get('factor', '')}")
                if stage in ("L2", "L3") and wr >= 0.55:
                    return {
                        "win_probability": round(1.0 - wr, 3),
                        "expected_return_pct": -0.5,
                        "max_drawdown_risk": 0.9,
                        "veto": True,
                        "reason": f"learn_veto:{d.get('factor', '')}",
                    }

        avoid = str(profile.get("avoid_hint", "") or "").lower()
        if avoid and direction in ("long", "short"):
            bad_long = direction == "long" and any(
                p in avoid for p in ("long açma", "chase", "crowded long", "rsi")
            )
            bad_short = direction == "short" and "short" in avoid
            if bad_long or bad_short:
                base_wr *= 0.82
                reasons.append("avoid_hint")

    regime = str(ctx.get("regime") or feat.get("regime") or "")
    if regime == "volatile":
        base_wr *= 0.92
        reasons.append("volatile_regime")
    elif regime == "trending_up" and direction == "long":
        base_wr = min(0.72, base_wr * 1.04)
    elif regime == "trending_down" and direction == "short":
        base_wr = min(0.72, base_wr * 1.04)

    drift = str(ctx.get("drift_status") or feat.get("drift_status") or "STABLE")
    if drift == "SHOCK":
        base_wr *= 0.75
        reasons.append("shock_drift")
    elif drift == "DRIFTING":
        base_wr *= 0.9

    crisis = int(ctx.get("crisis_level", 0) or 0)
    if crisis >= 3:
        base_wr *= 0.85
        reasons.append(f"crisis_{crisis}")

    exp_ret = (base_wr - 0.5) * 3.6
    dd_risk = max(0.1, min(0.95, 1.0 - base_wr + (0.1 if drift != "STABLE" else 0)))

    return {
        "win_probability": round(base_wr, 3),
        "expected_return_pct": round(exp_ret, 2),
        "max_drawdown_risk": round(dd_risk, 2),
        "veto": base_wr < 0.42 and len(reasons) >= 2,
        "reason": "|".join(reasons[:4]) or "neutral",
    }
