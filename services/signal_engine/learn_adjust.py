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
        (direction == "long" and effect in ("long_edge", "up"))
        or (direction == "short" and effect in ("short_edge", "down"))
    )
    opposed = (
        (direction == "long" and effect in ("short_edge", "down"))
        or (direction == "short" and effect in ("long_edge", "up"))
    )

    note = ""
    if aligned and wr >= 0.52:
        confidence = min(0.95, confidence * (1.0 + 0.1 * wr))
        note = f"learn+:{factor}"
    elif opposed and wr >= 0.52:
        confidence = max(0.0, confidence * 0.78)
        note = f"learn-:{factor}"

    avoid = str(profile.get("avoid_hint", "") or "")
    avoid_low = avoid.lower()
    entry_only = (
        "agresif boyut",
        "açma:",
        "long açma",
        "chase",
        "crowded long",
    )
    if avoid and direction in ("long", "short"):
        if any(p in avoid_low for p in entry_only):
            confidence *= 0.88
            note = (note + "|avoid_entry").lstrip("|")
        elif opposed:
            confidence *= 0.9

    stage = profile.get("learning_stage", "L0")
    if stage == "L3" and aligned:
        confidence = min(0.95, confidence * 1.04)
    elif stage == "L0" and direction != "flat":
        confidence *= 0.96

    return round(confidence, 4), note


def check_learn_veto(direction: str, learn_raw: str | None) -> tuple[bool, str]:
    """Hard block new entries when L2+ profile strongly opposes direction."""
    if not learn_raw or direction not in ("long", "short"):
        return False, ""

    try:
        profile = json.loads(learn_raw)
    except json.JSONDecodeError:
        return False, ""

    stage = str(profile.get("learning_stage", "L0"))
    if stage not in ("L2", "L3"):
        return False, ""

    drivers = profile.get("drivers") or []
    if not drivers:
        return False, ""

    top = drivers[0]
    effect = top.get("effect", "")
    wr = float(top.get("win_rate", 0) or 0)
    opposed = (
        (direction == "long" and effect in ("short_edge", "down"))
        or (direction == "short" and effect in ("long_edge", "up"))
    )
    if opposed and wr >= 0.55:
        return True, f"learn_veto_{top.get('factor', 'pattern')}_wr{int(wr * 100)}"

    return False, ""
