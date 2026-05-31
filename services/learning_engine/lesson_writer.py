"""Write learning output to Redis for agents, signals, and dashboard."""

from __future__ import annotations

import hashlib
import json
import time

import redis.asyncio as aioredis

STAGE_LABELS = {
    "L0": "Keşif — veri toplanıyor",
    "L1": "Desen — ilk faktörler",
    "L2": "Kalibre — LLM sentez aktif",
    "L3": "Uzman — derin coin modeli",
}


def profile_to_lesson_text(profile: dict) -> str:
    stage = profile.get("learning_stage", "L0")
    parts = [
        f"[Öğrenme {stage}] {profile.get('symbol', '')} rejim={profile.get('current_regime', '?')}",
        f"Giriş: {profile.get('best_entry_hint', '')}",
        f"Kaçın: {profile.get('avoid_hint', '')}",
    ]
    ai = profile.get("ai_insight")
    if ai:
        parts.append(f"AI: {ai}")
    for d in profile.get("drivers", [])[:2]:
        parts.append(
            f"{d.get('label', d.get('factor'))}: %{d.get('avg_move_pct', 0):.2f} "
            f"(WR {d.get('win_rate', 0)*100:.0f}%, n={d.get('samples', 0)})"
        )
    return " | ".join(p for p in parts if p)


def _lesson_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


async def persist_profile(
    redis: aioredis.Redis,
    profile: dict,
    extra_lessons: list[str] | None = None,
    *,
    force_lesson: bool = False,
):
    symbol = profile["symbol"]
    stage = profile.get("learning_stage", "L0")
    profile["stage_label"] = STAGE_LABELS.get(stage, stage)

    lesson_text = profile_to_lesson_text(profile)
    h = _lesson_hash(lesson_text)
    profile["_lesson_hash"] = h

    await redis.set(f"learn:profile:{symbol}", json.dumps(profile), ex=86400 * 7)

    write_lesson = force_lesson or bool(extra_lessons)
    if not write_lesson:
        prev = await redis.get(f"learn:last_hash:{symbol}")
        if prev != h:
            write_lesson = True

    if write_lesson:
        await redis.set(f"learn:last_hash:{symbol}", h, ex=86400)
        payload = json.dumps({
            "source": "learning_engine",
            "symbol": symbol,
            "text": lesson_text,
            "error_category": "live_behavior",
            "was_winner": True,
            "pnl_pct": 0,
            "profile": {
                "learning_stage": stage,
                "depth_score": profile.get("depth_score"),
                "ai_insight": profile.get("ai_insight"),
            },
            "ts": time.time(),
        })
        await redis.lpush(f"trade:lessons:{symbol}", payload)
        await redis.ltrim(f"trade:lessons:{symbol}", 0, 29)

    for line in extra_lessons or []:
        if not line or len(line) < 8:
            continue
        line_h = _lesson_hash(line)
        dedupe_key = f"learn:dedupe:{symbol}:{line_h}"
        if await redis.set(dedupe_key, "1", nx=True, ex=3600):
            await redis.lpush(
                f"trade:lessons:{symbol}",
                json.dumps({
                    "source": "learning_engine",
                    "symbol": symbol,
                    "text": line if line.startswith("[") else f"[Olay] {line}",
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
    stage_counts: dict[str, int] = {}
    llm_enriched = 0

    for learner in learners.values():
        p = learner.build_profile()
        r = p.get("current_regime", "unknown")
        regime_counts[r] = regime_counts.get(r, 0) + 1
        st = p.get("learning_stage", "L0")
        stage_counts[st] = stage_counts.get(st, 0) + 1
        if p.get("ai_insight"):
            llm_enriched += 1
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
        "stage_distribution": stage_counts,
        "llm_enriched_symbols": llm_enriched,
        "top_drivers": top_factors,
        "message": (
            f"{len(learners)} coin · L3 uzman: {stage_counts.get('L3', 0)} · "
            f"LLM özet: {llm_enriched} · güçlü faktör: "
            f"{top_factors[0]['factor'] if top_factors else 'toplanıyor'}"
        ),
    }
    await redis.set("learn:global:v1", json.dumps(global_state), ex=300)
    await redis.set("system:heartbeat:learning_engine", str(time.time()), ex=120)
