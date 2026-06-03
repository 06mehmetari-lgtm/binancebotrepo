#!/usr/bin/env python3
"""
Canlı LLM anahtar testi — Groq + Cerebras rotasyon.
Sunucuda:
  docker cp scripts/probe-llm-keys.py prometheus_agents:/tmp/probe_llm_keys.py
  docker compose exec agent_system python3 /tmp/probe_llm_keys.py
"""
from __future__ import annotations

import os
import sys

# agent_system / learning_engine container
for p in ("/app", os.path.join(os.path.dirname(__file__), "..", "services")):
    if os.path.isdir(p):
        sys.path.insert(0, p)

from llm_providers import (  # noqa: E402
    _DEFAULT_MODELS,
    _OPENAI_PROVIDERS,
    _is_rate_limited,
    _openai_chat,
    collect_keys,
)


def probe_provider(pid: str) -> None:
    prefix, base, model_env = _OPENAI_PROVIDERS[pid]
    model = (os.getenv(model_env) or _DEFAULT_MODELS.get(pid, "")).strip()
    keys = collect_keys(prefix)
    print(f"\n{'=' * 60}")
    print(f"{pid.upper()} — {len(keys)} key(s) — model={model}")
    print(f"{'=' * 60}")
    if not keys:
        print("  SKIP: no keys in environment")
        return
    ok = fail = rate = 0
    for idx, key in enumerate(keys):
        name = f"{prefix}" if idx == 0 and os.getenv(prefix) else f"{prefix}_{idx + 1}"
        if not name.startswith(prefix):
            name = f"{prefix}_{idx + 1}"
        # match collect_keys order: primary first, then _1.._n
        if idx == 0 and (os.getenv(prefix) or "").strip() == key:
            name = prefix
        elif len(keys) > 1:
            name = f"{prefix}_{idx + 1}" if (os.getenv(f"{prefix}_{idx + 1}") or "").strip() == key else name
        try:
            text = _openai_chat(
                base_url=base,
                api_key=key,
                model=model,
                prompt="Reply with exactly one word: OK",
                max_tokens=16,
                temperature=0,
            )
            snippet = (text or "").strip().replace("\n", " ")[:60]
            print(f"  OK   {name}  response={snippet!r}")
            ok += 1
        except Exception as e:
            if _is_rate_limited(e):
                print(f"  429  {name}  rate limited (key valid, try later)")
                rate += 1
            else:
                print(f"  FAIL {name}  {e}")
                fail += 1
    print(f"  → {ok} OK, {rate} rate-limited, {fail} failed (total {len(keys)})")


def main() -> None:
    print("LLM key probe — live API ping (not just .env presence)")
    print(f"LLM_PROVIDER_ORDER={os.getenv('LLM_PROVIDER_ORDER', '(default)')}")
    probe_provider("groq")
    probe_provider("cerebras")
    print("\nDone.")


if __name__ == "__main__":
    main()
