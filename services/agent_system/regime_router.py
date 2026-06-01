"""
Regime Router — Phase 3.
Maps market regime to agent weight profiles.
trending_up  → amplify bull/technical, dampen bear
trending_down → amplify bear/technical, dampen bull
ranging       → amplify neutral/sentiment, dampen directional
volatile      → amplify risk/macro, strongly dampen directional
"""
import logging

log = logging.getLogger(__name__)

# Per-regime weight multipliers (applied on top of DebateAgent.DEFAULT_WEIGHTS)
REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "trending_up": {
        "bull": 1.4, "technical": 1.2, "onchain": 1.2,
        "bear": 0.5,  "neutral": 0.9,  "risk": 0.9,
        "sentiment": 0.9, "macro": 0.9,
    },
    "trending_down": {
        "bear": 1.4, "technical": 1.2, "onchain": 1.2,
        "bull": 0.5, "neutral": 0.9,   "risk": 1.0,
        "sentiment": 0.9, "macro": 0.9,
    },
    "ranging": {
        "neutral": 1.3,  "sentiment": 1.1, "onchain": 1.1,
        "technical": 0.8, "bull": 0.85,    "bear": 0.85,
        "risk": 1.0, "macro": 0.9,
    },
    "volatile": {
        "risk": 1.5, "macro": 1.3, "neutral": 1.1,
        "bull": 0.45, "bear": 0.45, "technical": 0.9,
        "onchain": 1.0, "sentiment": 0.7,
    },
}

DEFAULT_WEIGHTS = {
    "technical": 1.0, "onchain": 1.2, "sentiment": 0.8,
    "macro": 0.9, "news": 0.8, "bull": 1.0, "bear": 1.0,
    "neutral": 0.7, "risk": 1.1,
}


def get_weights_for_regime(regime: str, learned_weights: dict | None = None) -> dict[str, float]:
    """
    Compute final agent weights by combining:
      1. Default base weights
      2. Per-regime multipliers
      3. Online-learned accuracy weights (from DebateAgent.update_weights)
    """
    multipliers = REGIME_WEIGHTS.get(regime, {})
    base = dict(learned_weights) if learned_weights else dict(DEFAULT_WEIGHTS)

    result: dict[str, float] = {}
    for agent, base_w in base.items():
        mult = multipliers.get(agent, 1.0)
        # Clamp to [0.2, 2.5] to prevent extreme suppression or amplification
        result[agent] = round(max(0.2, min(2.5, base_w * mult)), 3)

    if multipliers and regime != "unknown":
        log.debug(f"RegimeRouter: {regime} → weights adjusted for {len(result)} agents")

    return result
