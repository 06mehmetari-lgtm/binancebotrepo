"""Açık pozisyon — planlı / canlı / tahmin eğrisi ve uyumsuzluk skoru."""

from __future__ import annotations

import time
from typing import Any


def _decision(signal: dict) -> dict:
    return signal.get("decision") or {}


def _outcome(signal: dict) -> dict:
    return (signal.get("ensemble") or {}).get("outcome") or {}


def price_at_pct(entry: float, direction: str, pct: float) -> float:
    if entry <= 0:
        return 0.0
    if direction == "long":
        return round(entry * (1 + pct / 100.0), 8)
    return round(entry * (1 - pct / 100.0), 8)


def build_entry_plan(entry: float, direction: str, signal: dict) -> dict:
    """Giriş anı planı — stop, TP kademeleri, planlı fiyat eğrisi."""
    decision = _decision(signal)
    outcome = _outcome(signal)
    ladder = signal.get("take_profit_tiers") or decision.get("take_profit_tiers_pct") or [0.5, 2.0, 5.0]
    sl_pct = float(decision.get("stop_loss_pct") or signal.get("stop_loss_pct") or 1.2)
    tp_prices = decision.get("take_profit") or []
    if not tp_prices and entry > 0:
        tp_prices = [price_at_pct(entry, direction, float(t)) for t in ladder[:4]]

    entry_ts = time.time()
    horizon_sec = 3600.0
    planned_curve: list[dict[str, Any]] = []
    tp0 = float(ladder[0]) if ladder else 0.5
    steps = 60
    for i in range(steps + 1):
        elapsed = (horizon_sec / steps) * i
        prog = min(1.0, elapsed / horizon_sec)
        # Planlı kâr yolu — girişte beklenen yumuşak yükseliş/düşüş
        move_pct = tp0 * (prog ** 0.65)
        planned_curve.append({
            "ts": entry_ts + elapsed,
            "elapsed_sec": elapsed,
            "price": price_at_pct(entry, direction, move_pct),
            "pnl_pct": move_pct if direction == "long" else move_pct,
            "kind": "planned",
        })

    return {
        "entry": entry,
        "entry_ts": entry_ts,
        "direction": direction,
        "stop_loss": decision.get("stop_loss") or price_at_pct(entry, direction, -sl_pct),
        "stop_loss_pct": sl_pct,
        "take_profit_prices": tp_prices,
        "take_profit_tiers_pct": [float(x) for x in ladder[:4]],
        "win_probability": outcome.get("win_probability"),
        "expected_return_pct": outcome.get("expected_return_pct"),
        "planned_curve": planned_curve,
        "horizon_sec": horizon_sec,
        "reasons": (decision.get("reason") or signal.get("decision_reasons") or [])[:6],
    }


def planned_price_now(trade_plan: dict, entry_ts: float, direction: str, entry: float) -> float:
    """Giriş planına göre şu an beklenen fiyat."""
    if not trade_plan:
        return entry
    elapsed = max(0.0, time.time() - entry_ts)
    curve = trade_plan.get("planned_curve") or []
    if curve:
        best = curve[0]
        for pt in curve:
            if float(pt.get("elapsed_sec", 0)) <= elapsed:
                best = pt
            else:
                break
        return float(best.get("price") or entry)
    horizon = float(trade_plan.get("horizon_sec") or 3600)
    tp0 = float((trade_plan.get("take_profit_tiers_pct") or [0.5])[0])
    prog = min(1.0, elapsed / horizon)
    move = tp0 * (prog ** 0.65)
    return price_at_pct(entry, direction, move)


def build_forecast_curve(
    current_price: float,
    direction: str,
    signal: dict | None,
    *,
    points: int = 48,
    step_sec: float = 30.0,
) -> list[dict[str, Any]]:
    """Sistem tahmini — outcome + decision ile gelecek eğri."""
    if current_price <= 0:
        return []
    decision = _decision(signal or {})
    outcome = _outcome(signal or {})
    exp_ret = float(
        outcome.get("expected_return_pct")
        or decision.get("expected_return_pct")
        or 0.8
    )
    win_p = float(outcome.get("win_probability") or 0.55)
    risk = float(outcome.get("max_drawdown_risk") or decision.get("risk_score") or 0.3)
    # Kâr odaklı: beklenen getiri × güven, risk ile discount
    target_pct = exp_ret * win_p * (1.0 - min(risk, 0.5))
    regime_strength = float(signal.get("regime_strength") or 0.5) if signal else 0.5
    target_pct *= 0.7 + 0.3 * regime_strength

    now = time.time()
    curve: list[dict[str, Any]] = []
    for i in range(points):
        t = now + i * step_sec
        prog = i / max(points - 1, 1)
        move = target_pct * (prog ** 0.85)
        if direction == "long":
            p = current_price * (1 + move / 100.0)
        else:
            p = current_price * (1 - move / 100.0)
        curve.append({
            "ts": t,
            "price": round(p, 8),
            "pnl_pct": round(move, 4),
            "kind": "forecast",
            "confidence": round(win_p, 3),
        })
    return curve


def mismatch_score(live_price: float, planned_price: float, forecast_price: float | None = None) -> dict:
    """Plan vs canlı uyumsuzluk — renklendirme için."""
    if live_price <= 0 or planned_price <= 0:
        return {"pct": 0.0, "severity": "ok", "vs_planned": 0.0, "vs_forecast": 0.0}
    vs_planned = ((live_price - planned_price) / planned_price) * 100.0
    vs_forecast = 0.0
    if forecast_price and forecast_price > 0:
        vs_forecast = ((live_price - forecast_price) / forecast_price) * 100.0
    pct = abs(vs_planned)
    if pct >= 1.2:
        severity = "critical"
    elif pct >= 0.55:
        severity = "warn"
    elif pct >= 0.25:
        severity = "drift"
    else:
        severity = "ok"
    return {
        "pct": round(pct, 4),
        "severity": severity,
        "vs_planned": round(vs_planned, 4),
        "vs_forecast": round(vs_forecast, 4),
    }
