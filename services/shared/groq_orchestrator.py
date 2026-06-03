"""
Groq orchestration: one API key (or many for rate limits) × many model names from .env pools.
Pools: fast, main, reason, risk, learning, final, vision, fallback.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

GROQ_BASE = "https://api.groq.com/openai/v1"

# pool_id -> env prefix (first model = PREFIX, more = PREFIX_2, PREFIX_3, ...)
MODEL_POOL_PREFIX: dict[str, str] = {
    "fast": "GROQ_FAST_MODELS",
    "main": "GROQ_MAIN_MODELS",
    "reason": "GROQ_REASON_MODELS",
    "risk": "GROQ_RISK_MODELS",
    "learning": "GROQ_LEARNING_MODELS",
    "final": "GROQ_FINAL_MODEL",
    "vision": "GROQ_VISION_MODELS",
    "fallback": "GROQ_FALLBACK_MODEL",
}

_LEGACY_POOL_MODEL: dict[str, str] = {
    "learning": "GROQ_LEARN_MODEL",
    "final": "GROQ_DEBATE_MODEL",
}

_key_lock = threading.Lock()
_key_idx = 0
_model_idx: dict[str, int] = {}


def _model_slots() -> int:
    try:
        return max(2, min(32, int(os.getenv("GROQ_MODEL_SLOTS", "20"))))
    except ValueError:
        return 20


def collect_models(prefix: str) -> list[str]:
    """PREFIX, PREFIX_2 .. PREFIX_N (Groq .env convention)."""
    seen: set[str] = set()
    out: list[str] = []
    primary = (os.getenv(prefix, "") or "").strip()
    if primary and primary not in seen:
        seen.add(primary)
        out.append(primary)
    for i in range(2, _model_slots() + 1):
        m = (os.getenv(f"{prefix}_{i}", "") or "").strip()
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def models_for_pool(pool: str) -> list[str]:
    prefix = MODEL_POOL_PREFIX.get(pool)
    if not prefix:
        return []
    models = collect_models(prefix)
    if not models:
        legacy = _LEGACY_POOL_MODEL.get(pool)
        if legacy:
            v = (os.getenv(legacy, "") or "").strip()
            if v:
                models = [v]
    from llm_providers import resolve_model

    return [resolve_model("groq", m) for m in models]


def groq_keys() -> list[str]:
    from llm_providers import collect_keys

    return collect_keys("GROQ_API_KEY")


def _next_key() -> str:
    keys = groq_keys()
    if not keys:
        return ""
    global _key_idx
    with _key_lock:
        k = keys[_key_idx % len(keys)]
        _key_idx += 1
    return k


def _pool_models_round_robin(pool: str) -> list[str]:
    models = models_for_pool(pool)
    if not models:
        return []
    start = _model_idx.get(pool, 0)
    ordered = models[start:] + models[:start]
    _model_idx[pool] = (start + 1) % len(models)
    return ordered


def _is_rate_limited(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
        return True
    msg = str(exc).lower()
    return any(x in msg for x in ("429", "rate", "quota", "limit", "too many", "decommissioned"))


def _is_model_error(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 404, 422):
        return True
    msg = str(exc).lower()
    return any(x in msg for x in ("model", "not found", "decommissioned", "invalid", "does not exist"))


def groq_chat(
    *,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: float | None = None,
) -> str:
    if not api_key:
        raise RuntimeError("missing Groq API key")
    to = timeout if timeout is not None else float(os.getenv("AI_REQUEST_TIMEOUT", "45"))
    url = f"{GROQ_BASE}/chat/completions"
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=to) as resp:
        body = json.loads(resp.read())
    return (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""


def _bool_env(name: str, default: bool = True) -> bool:
    return (os.getenv(name, "true" if default else "false") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def chat_pool(
    pool: str,
    prompt: str,
    *,
    max_tokens: int = 280,
    temperature: float = 0.35,
) -> tuple[str | None, str | None]:
    """
    Try models in pool with round-robin API keys. On failure try next model/key.
    Returns (text, label) e.g. groq/final/llama-3.1-70b-versatile#key2
    """
    if not groq_keys():
        return None, None

    max_retry = max(1, int(os.getenv("AI_MAX_RETRY", "5")))
    pools_to_try = [pool]
    if _bool_env("AI_ENABLE_FALLBACK", True) and pool != "fallback":
        pools_to_try.append("fallback")

    attempts = 0
    for pname in pools_to_try:
        for model in _pool_models_round_robin(pname):
            if attempts >= max_retry * 3:
                break
            key = _next_key()
            attempts += 1
            label = f"groq/{pname}/{model}"
            try:
                text = groq_chat(
                    api_key=key,
                    model=model,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                if text.strip():
                    return text, label
            except Exception as e:
                if _is_model_error(e):
                    logger.debug("Groq model skip %s: %s", model, e)
                    continue
                if _is_rate_limited(e):
                    logger.debug("Groq rate limit %s", model)
                    continue
                if _bool_env("AI_ENABLE_AUTO_RETRY", True):
                    continue
                logger.debug("%s: %s", label, e)
    return None, None


def _parse_signal_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def swarm_consensus(
    pool: str,
    prompt: str,
    *,
    max_tokens: int = 200,
    temperature: float = 0.15,
) -> tuple[str | None, str | None]:
    """
    Parallel Groq calls across models in pool; majority vote on signal JSON.
    Requires AI_MINIMUM_MODEL_VOTE successful parses.
    """
    if not _bool_env("AI_ENABLE_SWARM", True):
        return chat_pool(pool, prompt, max_tokens=max_tokens, temperature=temperature)

    models = models_for_pool(pool)
    if not models:
        return chat_pool(pool, prompt, max_tokens=max_tokens, temperature=temperature)

    min_votes = max(1, int(os.getenv("AI_MINIMUM_MODEL_VOTE", "3")))
    min_conf = float(os.getenv("AI_REQUIRED_CONFIDENCE", "0.72"))
    parallel = max(1, min(int(os.getenv("AI_MAX_PARALLEL_REQUEST", "12")), len(models)))
    use_models = models[:parallel]

    votes: list[dict] = []

    def _one(model: str) -> dict | None:
        key = _next_key()
        if not key:
            return None
        try:
            raw = groq_chat(
                api_key=key,
                model=model,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            data = _parse_signal_json(raw)
            if not data:
                return None
            sig = str(data.get("signal", "flat")).lower()
            if sig not in ("long", "short", "flat"):
                return None
            conf = float(data.get("confidence", 0.5))
            return {
                "signal": sig,
                "confidence": conf,
                "reasoning": data.get("reasoning", ""),
                "model": model,
            }
        except Exception as e:
            logger.debug("swarm %s: %s", model, e)
            return None

    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futs = {ex.submit(_one, m): m for m in use_models}
        for fut in as_completed(futs):
            r = fut.result()
            if r:
                votes.append(r)

    if len(votes) < min_votes:
        return chat_pool(pool, prompt, max_tokens=max_tokens, temperature=temperature)

    counts: dict[str, list[float]] = {"long": [], "short": [], "flat": []}
    reasons: list[str] = []
    for v in votes:
        counts[v["signal"]].append(v["confidence"])
        if v.get("reasoning"):
            reasons.append(f"{v['model']}: {v['reasoning']}")

    winner = max(counts.keys(), key=lambda s: len(counts[s]))
    if len(counts[winner]) < min_votes:
        return chat_pool(pool, prompt, max_tokens=max_tokens, temperature=temperature)

    avg_conf = sum(counts[winner]) / len(counts[winner])
    if avg_conf < min_conf and winner != "flat":
        winner = "flat"
        avg_conf = min(avg_conf, 0.5)

    payload = {
        "signal": winner,
        "confidence": round(avg_conf, 3),
        "reasoning": f"swarm {len(votes)} models, {len(counts[winner])} agree — "
        + (reasons[0] if reasons else winner),
    }
    label = f"groq/swarm/{pool}({len(votes)} votes)"
    return json.dumps(payload), label


def pool_status() -> dict[str, list[str]]:
    return {pid: models_for_pool(pid) for pid in MODEL_POOL_PREFIX}
