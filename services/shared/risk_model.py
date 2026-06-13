"""Risk decision layer — position size, stop hints, trade approval (math, not NN)."""

from __future__ import annotations

import json
import os


def evaluate_risk(
    direction: str,
    confidence: float,
    kelly_fraction: float,
    context: dict,
    features: dict | None,
    *,
    portfolio_usd: float | None = None,
    open_exposure_usd: float = 0.0,
    learn_raw: str | None = None,
    open_positions: list[dict] | None = None,
    daily_pnl_pct: float | None = None,
    symbol: str = "",
) -> dict:
    """
    Returns approved, position_size_pct, stop_loss_pct, take_profit_tiers, risk_score, reasons.
    Never bypasses immunity — OMS still calls immunity_system.check_order().
    """
    feat = features or {}
    ctx = context or {}
    reasons: list[str] = []

    try:
        cap = float(portfolio_usd or os.getenv("PORTFOLIO_VALUE", "10000"))
    except ValueError:
        cap = 10000.0

    try:
        from risk_limits import get_active_limits, is_paper_unlimited

        lim = get_active_limits()
        max_pos = lim.max_position_pct / 100.0 if lim.max_position_pct > 1 else lim.max_position_pct
        max_open = lim.max_open_positions
        paper = is_paper_unlimited()
    except Exception:
        max_pos = 0.05
        max_open = 3
        paper = True

    risk_score = 0.0
    regime = str(ctx.get("regime") or feat.get("regime") or "unknown")
    crisis = int(ctx.get("crisis_level", 0) or 0)
    drift = str(ctx.get("drift_status") or feat.get("drift_status") or "STABLE")
    atr = float(feat.get("atr_pct", feat.get("atr_14", 0)) or 0)
    vol_ratio = float(feat.get("volume_ratio", 1) or 1)

    if direction not in ("long", "short"):
        return {
            "approved": False,
            "position_size_pct": 0.0,
            "stop_loss_pct": 0.0,
            "take_profit_tiers": [],
            "risk_score": 1.0,
            "reasons": ["flat_direction"],
        }

    if crisis >= 4 and not paper:
        return _reject("crisis_level_4", 0.95)

    if drift == "SHOCK" and not paper:
        return _reject("shock_drift", 0.9)

    if crisis >= 3:
        risk_score += 0.25
        reasons.append("crisis_elevated")
    if crisis >= 2 and paper:
        risk_score += 0.30
        base_size_note = True
        reasons.append("crisis_reduce_size")
    else:
        base_size_note = False
    if drift == "DRIFTING":
        risk_score += 0.15
        reasons.append("drifting")
    if regime == "volatile":
        risk_score += 0.12
        reasons.append("volatile_regime")
    if atr > 3.5:
        risk_score += 0.18
        reasons.append("high_atr")
    if vol_ratio < 0.5:
        risk_score += 0.1
        reasons.append("low_liquidity")

    max_daily_loss = float(os.getenv("RISK_MAX_DAILY_LOSS_PCT", "0.03"))
    max_weekly_loss = float(os.getenv("RISK_MAX_WEEKLY_LOSS_PCT", "0.08"))
    if daily_pnl_pct is not None and daily_pnl_pct <= -max_daily_loss and not paper:
        return _reject("daily_drawdown_limit", 0.92)
    if daily_pnl_pct is not None and daily_pnl_pct <= -max_weekly_loss * 0.5:
        risk_score += 0.2
        reasons.append("weekly_drawdown_pressure")

    corr_penalty = _correlation_penalty(direction, symbol, open_positions or [])
    if corr_penalty >= 0.85 and not paper:
        return _reject("correlation_cluster", 0.88)
    if corr_penalty > 0.5:
        risk_score += corr_penalty * 0.25
        reasons.append("correlated_exposure")

    room_pct = max(0.0, 1.0 - (open_exposure_usd / cap) if cap > 0 else 0.0)
    if room_pct < 0.02 and not paper:
        return _reject("portfolio_full", 0.85)

    risk_per_trade = float(os.getenv("RISK_PER_TRADE_PCT", "0.01"))
    stop_est = 1.2 if regime not in ("volatile",) else 1.8
    kelly_cap = risk_per_trade / (stop_est / 100.0)
    base_size = min(kelly_fraction * confidence, max_pos, kelly_cap)
    if paper:
        base_size = max(base_size, 0.003)
    if base_size_note:
        base_size *= 0.45

    if learn_raw:
        try:
            profile = json.loads(learn_raw)
            stage = profile.get("learning_stage", "L0")
            drivers = profile.get("drivers") or []
            if drivers and stage in ("L2", "L3"):
                top = drivers[0]
                wr = float(top.get("win_rate", 0) or 0)
                effect = top.get("effect", "")
                opposed = (
                    (direction == "long" and effect in ("short_edge", "down"))
                    or (direction == "short" and effect in ("long_edge", "up"))
                )
                if opposed and wr >= 0.55:
                    return _reject(f"learn_opposed_{top.get('factor', '')}", 0.8)
                aligned = (
                    (direction == "long" and effect in ("long_edge", "up"))
                    or (direction == "short" and effect in ("short_edge", "down"))
                )
                if aligned and wr >= 0.52:
                    base_size = min(max_pos, base_size * 1.08)
                    reasons.append("learn_aligned")
        except json.JSONDecodeError:
            pass

    base_size = min(base_size, max_pos, room_pct)
    if base_size < 0.002 and not paper:
        return _reject("size_too_small", risk_score + 0.2)

    stop_loss = 1.2
    if regime == "volatile" or atr > 2.5:
        stop_loss = 1.8
    elif regime in ("trending_up", "trending_down"):
        stop_loss = 1.0

    stop_loss = stop_loss * (1.0 + risk_score * 0.3)
    try:
        from profit_rules import profit_tiers, PAPER_MIN_SIGNAL_CONFIDENCE
        take_profit = profit_tiers()
        min_conf = PAPER_MIN_SIGNAL_CONFIDENCE if paper else 0.52
    except ImportError:
        take_profit = [1.5, 3.0, 6.0, 12.0] if confidence >= 0.7 else [1.5, 3.0, 6.0]
        min_conf = 0.58 if paper else 0.52

    approved = risk_score < 0.72 and confidence >= min_conf
    if crisis >= 2 and paper and confidence < 0.65:
        approved = False
        reasons.append("crisis_low_conf")
    if not approved:
        reasons.append("risk_score_high" if risk_score >= 0.72 else "low_confidence")

    return {
        "approved": approved,
        "position_size_pct": round(base_size, 4),
        "position_size_usd": round(cap * base_size, 2),
        "stop_loss_pct": round(stop_loss, 2),
        "take_profit_tiers": take_profit,
        "risk_score": round(min(1.0, risk_score), 3),
        "max_open_positions": max_open,
        "reasons": reasons or ["ok"],
    }


def _correlation_penalty(direction: str, symbol: str, positions: list[dict]) -> float:
    """BTC+ETH+BNB aynı yönde full exposure → yüksek korelasyon riski."""
    if not positions or direction not in ("long", "short"):
        return 0.0
    majors = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"}
    same_dir = 0
    major_same = 0
    for p in positions:
        if p.get("direction") != direction:
            continue
        same_dir += 1
        if str(p.get("symbol", "")).upper() in majors:
            major_same += 1
    if same_dir >= 3 and major_same >= 2:
        return 0.9
    if symbol.upper() in majors and major_same >= 2:
        return 0.75
    if same_dir >= 2:
        return 0.45
    return 0.0


def _reject(code: str, risk_score: float) -> dict:
    return {
        "approved": False,
        "position_size_pct": 0.0,
        "position_size_usd": 0.0,
        "stop_loss_pct": 0.0,
        "take_profit_tiers": [],
        "risk_score": round(risk_score, 3),
        "reasons": [code],
    }
