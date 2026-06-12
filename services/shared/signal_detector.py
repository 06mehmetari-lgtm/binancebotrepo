"""Signal detection model — opportunity scanner from indicators + whale activity."""

from __future__ import annotations


def detect_signal(features: dict, context: dict | None = None) -> dict:
    """
    Returns signal (long|short|flat), confidence, reasons[].
    Complements agent ensemble — used as prior in signal_engine.
    """
    ctx = context or {}
    f = features or {}
    reasons: list[str] = []
    score = 0.0

    rsi = float(f.get("rsi_14", 50) or 50)
    macd = float(f.get("macd_hist", 0) or 0)
    bb = float(f.get("bb_position", 0.5) or 0.5)
    vol = float(f.get("volume_ratio", 1) or 1)
    imb = float(f.get("imbalance_5", f.get("ob_imbalance_1", 0)) or 0)
    spoof = float(f.get("spoof_score", 0) or 0)
    adx = float(f.get("adx", f.get("adx_14", 0)) or 0)
    regime = str(ctx.get("regime") or f.get("regime") or "")
    regime_strength = float(ctx.get("regime_strength", 0) or 0)

    if rsi < 32 and macd > 0:
        score += 0.35
        reasons.append("rsi_oversold_bounce")
    elif rsi > 68 and macd < 0:
        score -= 0.35
        reasons.append("rsi_overbought_fade")

    if bb < 0.15:
        score += 0.2
        reasons.append("bb_lower_band")
    elif bb > 0.85:
        score -= 0.2
        reasons.append("bb_upper_band")

    if vol > 1.4:
        score += 0.15 * (1 if macd >= 0 else -1)
        reasons.append("volume_spike")

    if imb > 0.28 and spoof < 0.4:
        score += 0.25
        reasons.append("whale_bid_pressure")
    elif imb < -0.28 and spoof < 0.4:
        score -= 0.25
        reasons.append("whale_ask_pressure")
    elif spoof > 0.55:
        score *= 0.6
        reasons.append("spoof_detected")

    if regime == "trending_up" and regime_strength > 0.55:
        score += 0.12
        reasons.append("regime_trend_up")
    elif regime == "trending_down" and regime_strength > 0.55:
        score -= 0.12
        reasons.append("regime_trend_down")
    elif regime == "volatile":
        score *= 0.75
        reasons.append("volatile_regime_penalty")

    if adx > 0.28:
        score *= 1.1

    if score > 0.22:
        signal = "long"
    elif score < -0.22:
        signal = "short"
    else:
        signal = "flat"

    confidence = min(0.92, max(0.0, abs(score) * 1.15 + 0.35))
    if signal == "flat":
        confidence = max(0.0, confidence * 0.5)

    return {
        "signal": signal,
        "confidence": round(confidence, 4),
        "score": round(score, 4),
        "reasons": reasons[:6],
    }
