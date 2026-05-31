"""Apply live learning profile as confidence prior on ensemble output."""

from __future__ import annotations

import json


def adjust_confidence(
    direction: str,
    confidence: float,
    learn_raw: str | None,
) -> tuple[float, str]:
    if not learn_raw or direction == "flat":
        return confidence, ""

    try:
        profile = json.loads(learn_raw)
    except json.JSONDecodeError:
        return confidence, ""

    drivers = profile.get("drivers") or []
    if not drivers:
        return confidence, ""

    top = drivers[0]
    effect = top.get("effect", "mixed")
    wr = float(top.get("win_rate", 0))
    factor = str(top.get("factor", ""))

    aligned = (
        (direction == "long" and effect == "up")
        or (direction == "short" and effect == "down")
    )
    opposed = (
        (direction == "long" and effect == "down")
        or (direction == "short" and effect == "up")
    )

    note = ""
    if aligned and wr >= 0.55:
        confidence = min(0.95, confidence * (1.0 + 0.08 * wr))
        note = f"learn+:{factor}"
    elif opposed and wr >= 0.55:
        confidence = max(0.0, confidence * 0.82)
        note = f"learn-:{factor}"

    avoid = profile.get("avoid_hint", "")
    if avoid and opposed:
        confidence *= 0.9

    return round(confidence, 4), note
