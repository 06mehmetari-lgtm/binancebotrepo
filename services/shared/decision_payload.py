"""Final trading decision JSON — signal_engine output contract for OMS/dashboard."""

from __future__ import annotations


def build_trading_decision(
    symbol: str,
    signal_dict: dict,
    *,
    price: float = 0.0,
) -> dict:
    """
    Unified decision object matching dashboard + OMS expectations.
    {
      action, confidence, entry, stop_loss, take_profit[], risk_score, reason[]
    }
    """
    direction = str(signal_dict.get("direction", "flat"))
    trade_action = str(signal_dict.get("trade_action", "none"))
    is_valid = bool(signal_dict.get("is_valid"))
    confidence = float(signal_dict.get("confidence", 0) or 0)
    risk = signal_dict.get("risk") or {}
    outcome = (signal_dict.get("ensemble") or {}).get("outcome") or {}

    if trade_action == "close":
        action = "CLOSE"
    elif trade_action == "hold":
        action = "HOLD"
    elif direction == "long" and is_valid:
        action = "BUY"
    elif direction == "short" and is_valid:
        action = "SELL"
    elif direction == "flat":
        action = "FLAT"
    else:
        action = "WAIT"

    stop_pct = float(signal_dict.get("stop_loss_pct") or risk.get("stop_loss_pct") or 1.2)
    tp_tiers = signal_dict.get("take_profit_tiers") or risk.get("take_profit_tiers") or [0.5, 2.0, 5.0]
    entry = round(price, 8) if price > 0 else None

    stop_loss = None
    take_profit: list[float] = []
    if entry and entry > 0 and direction in ("long", "short"):
        sl_dist = entry * (stop_pct / 100.0)
        if direction == "long":
            stop_loss = round(entry - sl_dist, 8)
            take_profit = [round(entry * (1 + t / 100.0), 8) for t in tp_tiers[:4]]
        else:
            stop_loss = round(entry + sl_dist, 8)
            take_profit = [round(entry * (1 - t / 100.0), 8) for t in tp_tiers[:4]]

    reasons = list(signal_dict.get("decision_reasons") or [])
    if signal_dict.get("reject_reason"):
        reasons.append(str(signal_dict["reject_reason"]))
    if not reasons and risk.get("reasons"):
        reasons.extend([str(r) for r in risk["reasons"] if r != "ok"])

    return {
        "symbol": symbol,
        "action": action,
        "direction": direction,
        "confidence": round(confidence, 4),
        "entry": entry,
        "stop_loss": stop_loss,
        "stop_loss_pct": stop_pct,
        "take_profit": take_profit,
        "take_profit_tiers_pct": tp_tiers,
        "risk_score": float(risk.get("risk_score", 0) or 0),
        "approved": bool(risk.get("approved", is_valid)),
        "position_size_pct": float(risk.get("position_size_pct", 0) or 0),
        "position_size_usd": risk.get("position_size_usd"),
        "win_probability": outcome.get("win_probability"),
        "expected_return_pct": outcome.get("expected_return_pct"),
        "max_drawdown_risk": outcome.get("max_drawdown_risk"),
        "regime": signal_dict.get("regime"),
        "regime_strength": signal_dict.get("regime_strength"),
        "reason": reasons[:8],
        "trade_action": trade_action,
        "is_valid": is_valid,
    }
