"""Write learning output to Redis for agents, signals, and dashboard."""

from __future__ import annotations

import json
import time

import redis.asyncio as aioredis


def profile_to_lesson_text(profile: dict) -> str:
    parts = [
        f"[Canlı öğrenme] Rejim: {profile.get('current_regime', '?')}",
        f"Giriş: {profile.get('best_entry_hint', '')}",
        f"Kaçın: {profile.get('avoid_hint', '')}",
    ]
    for d in profile.get("drivers", [])[:2]:
        parts.append(
            f"{d['factor']}: %{d.get('avg_move_pct', 0):.2f} hareket "
            f"(doğruluk {d.get('win_rate', 0)*100:.0f}%, n={d.get('samples', 0)})"
        )
    return " | ".join(p for p in parts if p)


async def persist_profile(redis: aioredis.Redis, profile: dict, extra_lessons: list[str] | None = None):
    symbol = profile["symbol"]
    await redis.set(f"learn:profile:{symbol}", json.dumps(profile), ex=86400 * 7)

    lesson_text = profile_to_lesson_text(profile)
    payload = json.dumps({
        "source": "learning_engine",
        "symbol": symbol,
        "text": lesson_text,
        "error_category": "live_behavior",
        "was_winner": True,
        "pnl_pct": 0,
        "profile": profile,
        "ts": time.time(),
    })
    await redis.lpush(f"trade:lessons:{symbol}", payload)
    await redis.ltrim(f"trade:lessons:{symbol}", 0, 29)

    for line in extra_lessons or []:
        if not line:
            continue
        await redis.lpush(
            f"trade:lessons:{symbol}",
            json.dumps({
                "source": "learning_engine",
                "symbol": symbol,
                "text": f"[Canlı] {line}",
                "error_category": "regime_event",
                "ts": time.time(),
            }),
        )
    await redis.ltrim(f"trade:lessons:{symbol}", 0, 29)

    await redis.publish(f"ch:learn:{symbol}", symbol)


async def persist_global(redis: aioredis.Redis, learners: dict):
    """Aggregate cross-market learning summary."""
    all_drivers: dict[str, list[float]] = {}
    regime_counts: dict[str, int] = {}
    for learner in learners.values():
        p = learner.build_profile()
        r = p.get("current_regime", "unknown")
        regime_counts[r] = regime_counts.get(r, 0) + 1
        for d in p.get("drivers", []):
            all_drivers.setdefault(d["factor"], []).append(d.get("win_rate", 0))

    top_factors = sorted(
        (
            {"factor": k, "avg_win_rate": sum(v) / len(v), "symbols": len(v)}
            for k, v in all_drivers.items()
            if len(v) >= 3
        ),
        key=lambda x: x["avg_win_rate"],
        reverse=True,
    )[:10]

    global_state = {
        "updated_at": time.time(),
        "symbols_tracked": len(learners),
        "regime_distribution": regime_counts,
        "top_drivers": top_factors,
        "message": (
            f"{len(learners)} coin izleniyor; en güçlü faktör: "
            f"{top_factors[0]['factor'] if top_factors else 'veri toplanıyor'}"
        ),
    }
    await redis.set("learn:global:v1", json.dumps(global_state), ex=300)
    await redis.set("system:heartbeat:learning_engine", str(time.time()), ex=120)
