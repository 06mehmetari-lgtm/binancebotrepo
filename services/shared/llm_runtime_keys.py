"""Runtime LLM API key overrides — Redis hot-reload from dashboard."""

from __future__ import annotations

import json
import time
from typing import Any

REDIS_KEY = "system:llm:key_overrides"
CHANNEL = "ch:llm:keys_updated"

_PREFIX_TO_PROVIDER: dict[str, str] = {
    "GROQ_API_KEY": "groq",
    "CEREBRAS_API_KEY": "cerebras",
    "GOOGLE_AI_API_KEY": "google",
    "GEMINI_API_KEY": "google",
    "OPENROUTER_API_KEY": "openrouter",
    "MISTRAL_API_KEY": "mistral",
    "ANTHROPIC_API_KEY": "anthropic",
}

_cache: dict[str, list[str]] = {}
_cache_ts: float = 0.0
CACHE_TTL_SEC = 30.0


def provider_for_prefix(prefix: str) -> str | None:
    return _PREFIX_TO_PROVIDER.get(prefix)


def apply_overrides(data: dict[str, Any] | None) -> None:
    """Apply override dict {groq: [keys], cerebras: [keys], ...}."""
    global _cache, _cache_ts
    out: dict[str, list[str]] = {}
    if data:
        for pid, raw in data.items():
            if pid in ("updated_at", "updated_by", "probe_results"):
                continue
            if not isinstance(raw, list):
                continue
            cleaned = [str(k).strip() for k in raw if str(k).strip()]
            if cleaned:
                out[str(pid)] = cleaned
    _cache = out
    _cache_ts = time.time()


def load_overrides_from_redis(raw: str | bytes | None) -> None:
    if not raw:
        apply_overrides({})
        return
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        apply_overrides(json.loads(raw))
    except json.JSONDecodeError:
        apply_overrides({})


def get_runtime_keys(provider_id: str) -> list[str]:
    return list(_cache.get(provider_id, []))


def runtime_keys_active() -> bool:
    return bool(_cache)


def merge_with_env_keys(prefix: str, env_keys: list[str]) -> list[str]:
    pid = provider_for_prefix(prefix)
    if pid:
        runtime = get_runtime_keys(pid)
        if runtime:
            return runtime
    return env_keys


def overrides_payload(
    groq: list[str] | None = None,
    cerebras: list[str] | None = None,
    google: list[str] | None = None,
    openrouter: list[str] | None = None,
    *,
    updated_by: str = "dashboard",
    probe_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "updated_at": time.time(),
        "updated_by": updated_by,
    }
    if groq:
        payload["groq"] = groq
    if cerebras:
        payload["cerebras"] = cerebras
    if google:
        payload["google"] = google
    if openrouter:
        payload["openrouter"] = openrouter
    if probe_results:
        payload["probe_results"] = probe_results
    return payload
