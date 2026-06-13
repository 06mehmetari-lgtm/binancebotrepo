"""Giriş kapısı — learning_engine derslerini shadow/OMS girişine uygular."""

from __future__ import annotations

import json


def _parse_profile(learn_raw: str | None) -> dict:
    if not learn_raw:
        return {}
    try:
        p = json.loads(learn_raw)
        return p if isinstance(p, dict) else {}
    except json.JSONDecodeError:
        return {}


def check_learn_veto(direction: str, learn_raw: str | None) -> tuple[bool, str]:
    if direction not in ("long", "short"):
        return False, ""
    profile = _parse_profile(learn_raw)
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


def entry_size_multiplier(direction: str, learn_raw: str | None) -> tuple[float, str]:
    """Zarar derslerine göre boyut çarpanı — veto değil, küçültme."""
    if direction not in ("long", "short"):
        return 1.0, ""
    profile = _parse_profile(learn_raw)
    mult = 1.0
    notes: list[str] = []

    stage = str(profile.get("learning_stage", "L0"))
    if stage in ("L1", "L2", "L3"):
        wr = float(profile.get("win_rate", 0) or 0)
        if wr < 0.45 and profile.get("trades", 0) >= 3:
            mult *= 0.82
            notes.append("dusuk_wr")

    avoid = str(profile.get("avoid_hint", "") or "").lower()
    if avoid:
        bad = (
            (direction == "long" and any(p in avoid for p in ("long açma", "chase", "crowded", "rsi")))
            or (direction == "short" and "short" in avoid)
        )
        if bad:
            mult *= 0.75
            notes.append("avoid_hint")

    drivers = profile.get("drivers") or []
    effect = ""
    wr = 0.0
    if drivers:
        top = drivers[0]
        effect = str(top.get("effect", ""))
        wr = float(top.get("win_rate", 0) or 0)
        opposed = (
            (direction == "long" and effect in ("short_edge", "down"))
            or (direction == "short" and effect in ("long_edge", "up"))
        )
        if opposed and wr >= 0.52 and stage in ("L1", "L2", "L3"):
            mult *= 0.7
            notes.append(f"opp_{top.get('factor', '')}")

    aligned = (
        (direction == "long" and effect in ("long_edge", "up"))
        or (direction == "short" and effect in ("short_edge", "down"))
    )
    if aligned and wr >= 0.55 and stage in ("L2", "L3"):
        mult = min(1.15, mult * 1.08)
        notes.append("learn_edge")

    return round(mult, 3), "|".join(notes) if notes else ""


def parse_last_lesson(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return str(obj.get("text") or obj.get("lesson") or "")[:200]
        return str(obj)[:200]
    except json.JSONDecodeError:
        return str(raw)[:200]


def entry_hints(profile: dict) -> dict:
    return {
        "learning_stage": str(profile.get("learning_stage", "L0")),
        "avoid_hint": str(profile.get("avoid_hint", "") or "")[:160],
        "best_entry_hint": str(profile.get("best_entry_hint", "") or "")[:160],
        "win_rate": float(profile.get("win_rate", 0) or 0),
        "trades": int(profile.get("trades", 0) or 0),
    }
