"""
Multi-source signal ensemble — agents + NEAT genome + PPO RL vote fusion.
Weights are env-configurable; disagreement reduces confidence (meta-learning lite).
"""

from __future__ import annotations

import os
from typing import Literal

Direction = Literal["long", "short", "flat"]

W_AGENT = float(os.getenv("ENSEMBLE_WEIGHT_AGENT", "0.55"))
W_NEAT = float(os.getenv("ENSEMBLE_WEIGHT_NEAT", "0.25"))
W_RL = float(os.getenv("ENSEMBLE_WEIGHT_RL", "0.20"))
MIN_CONFIDENCE = float(os.getenv("SIGNAL_MIN_CONFIDENCE", "0.60"))


def _vote_scores(direction: str, confidence: float) -> dict[str, float]:
    scores = {"long": 0.0, "short": 0.0, "flat": 0.0}
    d = direction if direction in scores else "flat"
    scores[d] = max(0.0, min(1.0, confidence))
    return scores


def fuse_sources(
    agent_direction: str,
    agent_confidence: float,
    neat_direction: str | None,
    neat_confidence: float,
    rl_direction: str | None,
    rl_confidence: float,
) -> tuple[Direction, float, str, dict]:
    """
    Returns direction, confidence, source label, diagnostics.
    """
    fused = {"long": 0.0, "short": 0.0, "flat": 0.0}
    weights_used: list[str] = []
    sources: list[tuple[str, float]] = []

    if agent_confidence > 0:
        w = W_AGENT
        for k, v in _vote_scores(agent_direction, agent_confidence).items():
            fused[k] += v * w
        weights_used.append("agent")
        sources.append(("agent", agent_confidence))

    if neat_direction and neat_confidence > 0:
        w = W_NEAT
        for k, v in _vote_scores(neat_direction, neat_confidence).items():
            fused[k] += v * w
        weights_used.append("neat")
        sources.append(("neat", neat_confidence))

    if rl_direction and rl_confidence > 0:
        w = W_RL
        for k, v in _vote_scores(rl_direction, rl_confidence).items():
            fused[k] += v * w
        weights_used.append("rl")
        sources.append(("rl", rl_confidence))

    total_w = sum(
        [
            W_AGENT if "agent" in weights_used else 0,
            W_NEAT if "neat" in weights_used else 0,
            W_RL if "rl" in weights_used else 0,
        ]
    ) or 1.0
    for k in fused:
        fused[k] /= total_w

    direction: Direction = max(fused, key=fused.__getitem__)  # type: ignore[assignment]
    confidence = fused[direction]

    # Penalize disagreement between active sources
    dirs = {s[0] for s in sources if s[1] >= 0.5}
    unique_dirs = {d for d in dirs if d != "flat"}
    if len(unique_dirs) > 1:
        confidence *= 0.75

    if confidence < MIN_CONFIDENCE:
        direction = "flat"

    source = "ensemble:" + "+".join(weights_used) if weights_used else "signal_engine"
    diagnostics = {
        "fused_scores": fused,
        "sources": sources,
        "weights": {"agent": W_AGENT, "neat": W_NEAT, "rl": W_RL},
    }
    return direction, round(confidence, 4), source, diagnostics
