"""Build LLM provider status from process env (for Redis → dashboard)."""

from __future__ import annotations

import time

POOL_LABELS = {
    "fast": "Fast",
    "main": "Main",
    "reason": "Reasoning",
    "risk": "Risk",
    "learning": "Learning",
    "final": "Final judge",
    "vision": "Vision",
    "fallback": "Fallback",
}


def build_llm_status_payload() -> dict:
    from llm_providers import collect_keys, status_snapshot
    from groq_orchestrator import pool_status

    providers = status_snapshot()
    for row in providers:
        pid = row["id"]
        count = row["key_count"]
        if count <= 0:
            continue
        if pid == "groq" and count > 0:
            row["env"] = f"GROQ_API_KEY_1..{count}"
        elif pid == "cerebras" and count > 0:
            row["env"] = f"CEREBRAS_API_KEY_1..{count}"

    pools_raw = pool_status()
    groq_pools = [
        {
            "id": pid,
            "label": POOL_LABELS.get(pid, pid),
            "count": len(models),
            "models": models,
        }
        for pid, models in pools_raw.items()
        if models
    ]

    any_ok = any(p["configured"] for p in providers)
    groq = next((p for p in providers if p["id"] == "groq"), None)

    try:
        from llm_runtime_keys import runtime_keys_active

        runtime_active = runtime_keys_active()
    except ImportError:
        runtime_active = False

    return {
        "updated_at": time.time(),
        "providers": providers,
        "groq_pools": groq_pools,
        "any_configured": any_ok,
        "groq_configured": bool(groq and groq["configured"]),
        "groq_key_count": groq["key_count"] if groq else 0,
        "runtime_keys_active": runtime_active,
    }
