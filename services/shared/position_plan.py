"""Açık pozisyon grafik beyni — blueprint / canlı / sürekli analiz / tahmin / konsensüs."""

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


def _curve_points(
    entry_ts: float,
    entry: float,
    direction: str,
    target_pct: float,
    *,
    horizon_sec: float = 3600.0,
    steps: int = 72,
    kind: str = "planned",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(steps + 1):
        elapsed = (horizon_sec / steps) * i
        prog = min(1.0, elapsed / horizon_sec)
        move = target_pct * (prog ** 0.65)
        out.append({
            "ts": entry_ts + elapsed,
            "elapsed_sec": elapsed,
            "price": price_at_pct(entry, direction, move),
            "pnl_pct": round(move, 4),
            "kind": kind,
        })
    return out


def build_entry_blueprint(entry: float, direction: str, signal: dict) -> dict:
    """
    AL derken dondurulan grafik — bir daha değişmez.
    Sistemin o anki tahmin yolu + nedenler + hedefler.
    """
    decision = _decision(signal)
    outcome = _outcome(signal)
    det = (signal.get("ensemble") or {}).get("signal_detector") or {}
    ladder = signal.get("take_profit_tiers") or decision.get("take_profit_tiers_pct") or [0.5, 2.0, 5.0]
    sl_pct = float(decision.get("stop_loss_pct") or signal.get("stop_loss_pct") or 1.2)
    tp_prices = decision.get("take_profit") or []
    if not tp_prices and entry > 0:
        tp_prices = [price_at_pct(entry, direction, float(t)) for t in ladder[:4]]

    exp_ret = float(outcome.get("expected_return_pct") or decision.get("expected_return_pct") or 0.8)
    win_p = float(outcome.get("win_probability") or 0.55)
    entry_ts = time.time()

    bullish = direction == "long"
    narrative = (
        f"{'LONG' if bullish else 'SHORT'} @ {entry} — "
        f"P(win) {win_p:.0%}, hedef +{exp_ret:.2f}% — "
        f"{', '.join(str(r) for r in (decision.get('reason') or signal.get('decision_reasons') or [])[:4])}"
    )

    return {
        "frozen_at": entry_ts,
        "entry": entry,
        "direction": direction,
        "action": decision.get("action") or ("BUY" if bullish else "SELL"),
        "confidence": float(signal.get("confidence") or decision.get("confidence") or 0),
        "regime": signal.get("regime"),
        "regime_strength": signal.get("regime_strength"),
        "stop_loss": decision.get("stop_loss") or price_at_pct(entry, direction, -sl_pct),
        "stop_loss_pct": sl_pct,
        "take_profit_prices": tp_prices,
        "take_profit_tiers_pct": [float(x) for x in ladder[:4]],
        "win_probability": win_p,
        "expected_return_pct": exp_ret,
        "reasons": (decision.get("reason") or signal.get("decision_reasons") or [])[:8],
        "signal_detector": det.get("signal"),
        "narrative": narrative[:500],
        "blueprint_curve": _curve_points(entry_ts, entry, direction, exp_ret * win_p, kind="blueprint"),
        "horizon_sec": 3600.0,
    }


def build_entry_plan(entry: float, direction: str, signal: dict) -> dict:
    """Güncel trade plan — blueprint ile aynı köken, operasyonel TP/stop."""
    bp = build_entry_blueprint(entry, direction, signal)
    return {
        "entry": entry,
        "entry_ts": bp["frozen_at"],
        "direction": direction,
        "stop_loss": bp["stop_loss"],
        "stop_loss_pct": bp["stop_loss_pct"],
        "take_profit_prices": bp["take_profit_prices"],
        "take_profit_tiers_pct": bp["take_profit_tiers_pct"],
        "win_probability": bp["win_probability"],
        "expected_return_pct": bp["expected_return_pct"],
        "planned_curve": bp["blueprint_curve"],
        "horizon_sec": bp["horizon_sec"],
        "reasons": bp["reasons"],
    }


def blueprint_price_now(blueprint: dict, entry_ts: float, entry: float, direction: str) -> float:
    if not blueprint:
        return entry
    elapsed = max(0.0, time.time() - entry_ts)
    curve = blueprint.get("blueprint_curve") or blueprint.get("planned_curve") or []
    if curve:
        best = curve[0]
        for pt in curve:
            if float(pt.get("elapsed_sec", 0)) <= elapsed:
                best = pt
            else:
                break
        return float(best.get("price") or entry)
    return entry


def planned_price_now(trade_plan: dict, entry_ts: float, direction: str, entry: float) -> float:
    return blueprint_price_now(trade_plan, entry_ts, entry, direction)


def build_forecast_curve(
    current_price: float,
    direction: str,
    signal: dict | None,
    *,
    points: int = 48,
    step_sec: float = 30.0,
) -> list[dict[str, Any]]:
    if current_price <= 0:
        return []
    decision = _decision(signal or {})
    outcome = _outcome(signal or {})
    exp_ret = float(outcome.get("expected_return_pct") or decision.get("expected_return_pct") or 0.8)
    win_p = float(outcome.get("win_probability") or 0.55)
    risk = float(outcome.get("max_drawdown_risk") or decision.get("risk_score") or 0.3)
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


def mismatch_score(
    live_price: float,
    planned_price: float,
    forecast_price: float | None = None,
    *,
    direction: str = "long",
) -> dict:
    if live_price <= 0 or planned_price <= 0:
        return {
            "pct": 0.0, "severity": "ok", "vs_planned": 0.0, "vs_forecast": 0.0,
            "aligned": True, "why": "veri yok",
        }
    vs_planned = ((live_price - planned_price) / planned_price) * 100.0
    vs_forecast = 0.0
    if forecast_price and forecast_price > 0:
        vs_forecast = ((live_price - forecast_price) / forecast_price) * 100.0

    # Yön duyarlı: long için plan altı = kötü
    if direction == "long":
        adverse = vs_planned < -0.15
        favorable = vs_planned > 0.1
    else:
        adverse = vs_planned > 0.15
        favorable = vs_planned < -0.1

    pct = abs(vs_planned)
    if pct >= 1.2:
        severity = "critical"
    elif pct >= 0.55:
        severity = "warn"
    elif pct >= 0.25:
        severity = "drift"
    else:
        severity = "ok"

    if adverse and severity in ("warn", "critical"):
        why = "plan altında — düşüş riski, stop sıkılaştır"
    elif favorable:
        why = "plan üstünde — kâr yolu, trailing düşün"
    elif severity == "drift":
        why = "hafif sapma — izle"
    else:
        why = "plan ile uyumlu"

    return {
        "pct": round(pct, 4),
        "severity": severity,
        "vs_planned": round(vs_planned, 4),
        "vs_forecast": round(vs_forecast, 4),
        "aligned": severity == "ok",
        "adverse": adverse,
        "favorable": favorable,
        "why": why,
    }


def rolling_analysis(
    ticks: list[dict],
    blueprint: dict,
    entry: float,
    entry_ts: float,
    direction: str,
    signal: dict | None,
) -> dict:
    """
    Alındıktan sonra sürekli analiz — canlı tick'lerden çıkan yorum.
    Üç grafik birbirini besler.
    """
    if not ticks:
        return {"status": "waiting", "points": [], "velocity_pct_per_min": 0, "narrative": "Tick bekleniyor"}

    recent = ticks[: min(120, len(ticks))]
    prices = [float(t.get("price") or 0) for t in recent if float(t.get("price") or 0) > 0]
    if len(prices) < 2:
        return {"status": "warming", "points": [], "velocity_pct_per_min": 0, "narrative": "Isınıyor"}

    latest = recent[0]
    live_p = float(latest.get("price") or prices[0])
    bp_p = blueprint_price_now(blueprint, entry_ts, entry, direction)
    forecast = build_forecast_curve(live_p, direction, signal, points=12, step_sec=30)
    fc_p = float(forecast[0]["price"]) if forecast else live_p
    mm = mismatch_score(live_p, bp_p, fc_p, direction=direction)

    # Hız: son 10 tick
    span_prices = prices[: min(10, len(prices))]
    if len(span_prices) >= 2:
        move = ((span_prices[0] - span_prices[-1]) / span_prices[-1]) * 100.0
        if direction == "short":
            move = -move
        velocity = move * 6  # ~10sn → dakika tahmini
    else:
        velocity = 0.0

    points = []
    for t in reversed(recent[:60]):
        ts = float(t.get("ts") or 0)
        p = float(t.get("price") or 0)
        if p <= 0:
            continue
        bp = blueprint_price_now(blueprint, entry_ts, entry, direction)
        delta_pct = ((p - bp) / bp * 100.0) if bp > 0 else 0
        points.append({
            "ts": ts,
            "price": p,
            "blueprint_price": bp,
            "delta_pct": round(delta_pct, 4),
            "upnl_pct": float(t.get("upnl_pct") or 0),
            "kind": "analysis",
        })

    upnl = float(latest.get("upnl_pct") or 0)
    if velocity > 0.15 and upnl > 0:
        trend = "yükseliş momentumu — kâr koruma"
    elif velocity < -0.15 and upnl < 0:
        trend = "düşüş momentumu — zarar kes riski"
    elif mm["adverse"]:
        trend = "plan dışı hareket — blueprint ile çelişki"
    elif mm["favorable"]:
        trend = "plan üstü — hedef yolunda"
    else:
        trend = "yatay — bekle"

    narrative = (
        f"Canlı {live_p:.6f} | Blueprint {bp_p:.6f} | Sapma {mm['vs_planned']:+.2f}% | "
        f"Hız ~{velocity:+.2f}%/dk | PnL {upnl:+.2f}% — {trend}"
    )

    return {
        "status": "active",
        "points": points,
        "velocity_pct_per_min": round(velocity, 4),
        "mismatch": mm,
        "trend": trend,
        "narrative": narrative,
        "live_price": live_p,
        "blueprint_price": bp_p,
        "forecast_price": fc_p,
    }


def chart_consensus(
    rolling: dict,
    upnl_pct: float,
    signal: dict | None,
) -> dict:
    """Üç grafik konsensüsü → al/sat/tut önerisi."""
    mm = rolling.get("mismatch") or {}
    severity = mm.get("severity", "ok")
    velocity = float(rolling.get("velocity_pct_per_min") or 0)
    adverse = bool(mm.get("adverse"))
    favorable = bool(mm.get("favorable"))

    action = "hold"
    urgency = "low"
    reasons: list[str] = []

    conf = float((signal or {}).get("confidence") or 0)
    trade_action = str((signal or {}).get("trade_action") or "hold")

    if severity == "critical" and adverse and upnl_pct < -0.3:
        action = "close"
        urgency = "critical"
        reasons.append("blueprint kritik sapma + zarar")
    elif severity == "critical" and adverse and upnl_pct >= 0.2:
        action = "take_partial"
        urgency = "high"
        reasons.append("plan bozuldu ama kârda — kısmi sat")
    elif severity == "warn" and adverse and upnl_pct < -0.5:
        action = "tighten_stop"
        urgency = "medium"
        reasons.append("plan altı + zarar — stop sıkı")
    elif favorable and upnl_pct >= 0.5 and velocity > 0.1:
        action = "trail_profit"
        urgency = "low"
        reasons.append("plan üstü momentum — trailing kâr")
    elif trade_action == "close" and conf >= 0.5:
        action = "close"
        urgency = "medium"
        reasons.append("sinyal motoru kapat öneriyor")
    elif favorable and upnl_pct > 0:
        action = "hold"
        reasons.append("kâr yolunda — tut")

    score = 0.5
    if favorable:
        score += 0.2
    if adverse:
        score -= 0.25
    if severity == "critical":
        score -= 0.3
    if upnl_pct > 0:
        score += min(0.2, upnl_pct / 10)
    score = max(0.0, min(1.0, score))

    return {
        "action": action,
        "urgency": urgency,
        "score": round(score, 3),
        "reasons": reasons[:5],
        "layers": {
            "blueprint": mm.get("why", ""),
            "velocity": f"{velocity:+.2f}%/dk",
            "signal": trade_action,
        },
    }
