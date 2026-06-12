"""Sequence-based regime scorer — lightweight proxy for LSTM/Transformer regime brain."""

from __future__ import annotations

def classify_regime_sequence(history: list[list[float]], current: list[float]) -> dict:
    """
    Input: history of feature vectors (rsi, macd, imb, funding, oi, ls, fg, vix).
    Output: regime label + strength 0-1 + manipulation/volatile flags.
    """
    if not current or len(current) < 4:
        return {"regime": "unknown", "strength": 0.0, "volatile": False, "manipulation": False}

    rsi = _clip(current[0], 0, 100) / 100.0
    macd = current[1] if len(current) > 1 else 0.0
    imb = current[2] if len(current) > 2 else 0.0
    funding = current[3] if len(current) > 3 else 0.0

    mom = 0.0
    vol_spike = 1.0
    if len(history) >= 8:
        past = history[-8]
        if past and past[0]:
            mom = (current[0] - past[0]) / 100.0
        if len(past) > 1 and past[1]:
            vol_spike = abs(macd - past[1]) / (abs(past[1]) + 1e-6)

    adx_proxy = abs(macd) * 12 + abs(imb) * 0.4
    trending_up = mom > 0.04 and macd > 0 and rsi > 0.48
    trending_down = mom < -0.04 and macd < 0 and rsi < 0.52
    volatile = vol_spike > 1.8 or abs(funding) > 0.003
    manipulation = abs(imb) > 0.45 and vol_spike > 2.5 and adx_proxy < 0.35
    ranging = adx_proxy < 0.25 and abs(mom) < 0.03

    if manipulation:
        regime = "manipulation"
        strength = min(0.9, 0.5 + abs(imb) * 0.5)
    elif volatile:
        regime = "volatile"
        strength = min(0.95, 0.55 + vol_spike * 0.1)
    elif trending_up:
        regime = "trending_up"
        strength = min(0.95, 0.5 + mom * 2 + adx_proxy * 0.2)
    elif trending_down:
        regime = "trending_down"
        strength = min(0.95, 0.5 + abs(mom) * 2 + adx_proxy * 0.2)
    elif ranging:
        regime = "ranging"
        strength = min(0.75, 0.45 + (0.25 - adx_proxy))
    else:
        regime = "ranging"
        strength = 0.4

    return {
        "regime": regime,
        "strength": round(max(0.0, min(1.0, strength)), 3),
        "volatile": volatile,
        "manipulation": manipulation,
        "momentum_8": round(mom, 4),
    }


def _clip(v: float, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, x))
