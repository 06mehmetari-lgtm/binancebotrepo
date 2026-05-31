"""Human-readable trade explanations for Redis and the dashboard."""

from __future__ import annotations

import json
from typing import Any

AGENT_LABELS: dict[str, str] = {
    "technical": "Technical — RSI, MACD, ADX, order-book imbalance",
    "onchain": "On-chain — funding, flows, liquidations",
    "sentiment": "Sentiment — Fear & Greed, Reddit",
    "macro": "Macro — VIX, DXY",
    "bull": "Bull — oversold / demand setups",
    "bear": "Bear — overbought / supply setups",
    "neutral": "Neutral — range / no clear trend",
    "risk": "Risk — crisis & drift guard",
}

REGIME_TR: dict[str, str] = {
    "trending_up": "yükseliş trendi",
    "trending_down": "düşüş trendi",
    "ranging": "yatay piyasa",
    "volatile": "yüksek volatilite",
}


def _fmt_reasoning(reasoning: Any) -> str:
    if reasoning is None:
        return ""
    if isinstance(reasoning, str):
        return reasoning
    if isinstance(reasoning, dict):
        parts = [f"{k}={v}" for k, v in reasoning.items() if v is not None]
        return ", ".join(parts)
    return str(reasoning)


def format_vote_reasoning(agent_name: str, signal: str, confidence: float, reasoning: Any) -> str:
    label = AGENT_LABELS.get(agent_name, agent_name)
    detail = _fmt_reasoning(reasoning)
    base = f"{label}: {signal.upper()} ({confidence:.0%})"
    return f"{base} — {detail}" if detail else base


def build_dissent_risk(votes: list[Any], final_signal: str) -> str:
    if final_signal == "flat":
        return "Sinyal bastırıldı — ajan konsensüsü yeterli değil veya risk ajanı FLAT önerdi."
    opposing = [v for v in votes if getattr(v, "signal", v.get("signal", "flat")) not in (final_signal, "flat")]
    if not opposing:
        return ""
    names = [getattr(v, "agent_name", v.get("agent", "?")) for v in opposing]
    return (
        f"{len(opposing)} ajan karşı görüşte ({', '.join(names)}). "
        f"Ağırlıklı oylama yine de {final_signal.upper()} yönünde."
    )


def build_probability_breakdown(
    votes: list[Any],
    final_signal: str,
    final_confidence: float,
    consensus_strength: float,
) -> dict[str, float]:
    scores = {"long": 0.0, "short": 0.0, "flat": 0.0}
    for v in votes:
        sig = getattr(v, "signal", v.get("signal", "flat"))
        conf = float(getattr(v, "confidence", v.get("confidence", 0.5)))
        if sig in scores:
            scores[sig] += conf
    total = sum(scores.values()) or 1.0
    return {
        "long_pct": round(scores["long"] / total * 100, 1),
        "short_pct": round(scores["short"] / total * 100, 1),
        "flat_pct": round(scores["flat"] / total * 100, 1),
        "ai_confidence_pct": round(final_confidence * 100, 1),
        "consensus_pct": round(consensus_strength * 100, 1),
        "selected_direction": final_signal,
    }


def build_consensus_reasoning(
    symbol: str,
    final_signal: str,
    final_confidence: float,
    majority_reasoning: str,
    features: dict,
    context: dict,
    lessons: list[str] | None = None,
) -> str:
    rsi = float(features.get("rsi_14", 50) or 50)
    macd = float(features.get("macd_hist", 0) or 0)
    regime = context.get("regime", "unknown")
    regime_tr = REGIME_TR.get(str(regime), str(regime))
    crisis = int(context.get("crisis_level", 0) or 0)
    drift = context.get("drift_status", features.get("drift_status", "STABLE"))
    fg = float(context.get("fear_greed", 50) or 50)

    lines = [
        f"{symbol}: {final_signal.upper()} sinyali — AI güven {final_confidence:.0%}.",
        f"Teknik: RSI {rsi:.1f}, MACD hist {macd:+.4f}. Rejim: {regime_tr}.",
        f"Risk: kriz seviyesi L{crisis}, drift {drift}, Fear&Greed {fg:.0f}.",
    ]
    if lessons:
        lines.append("Geçmiş işlemlerden: " + " | ".join(lessons[:3]))
    if majority_reasoning:
        lines.append(majority_reasoning)
    return " ".join(lines)


def build_trade_targets(
    direction: str,
    price: float,
    atr: float,
    confidence: float,
    kelly_fraction: float,
) -> dict[str, Any]:
    if direction == "flat" or not price or not atr:
        return {"entry": price, "stop_loss": None, "take_profit": None, "risk_reward": None}

    sl_mult, tp_mult = 2.0, 3.5
    if direction == "long":
        sl = price - atr * sl_mult
        tp = price + atr * tp_mult
    else:
        sl = price + atr * sl_mult
        tp = price - atr * tp_mult

    risk = abs(price - sl)
    reward = abs(tp - price)
    rr = round(reward / risk, 2) if risk > 0 else None

    return {
        "entry": round(price, 6),
        "stop_loss": round(sl, 6),
        "take_profit": round(tp, 6),
        "risk_reward": rr,
        "position_pct": round(min(kelly_fraction, 0.05) * 100, 2),
        "confidence_pct": round(confidence * 100, 1),
    }
