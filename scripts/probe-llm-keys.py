#!/usr/bin/env python3
"""
Canlı LLM anahtar testi — Groq + Cerebras (+ Ollama) rotasyon.
Sunucuda:
  docker cp scripts/probe-llm-keys.py prometheus_agents:/tmp/probe_llm_keys.py
  docker compose exec agent_system python3 /tmp/probe_llm_keys.py
"""
from __future__ import annotations

import os
import sys
import urllib.error

for p in ("/app", os.path.join(os.path.dirname(__file__), "..", "services")):
    if os.path.isdir(p):
        sys.path.insert(0, p)

from llm_providers import (  # noqa: E402
    _DEFAULT_MODELS,
    _OPENAI_PROVIDERS,
    _is_ip_blocked,
    _is_rate_limited,
    _openai_chat,
    _ollama_chat,
    http_error_detail,
    resolve_model,
)

# İlk anahtarda ek model dene (eski .env hâlâ 3.1-70b ise ayırt etmek için)
_GROQ_ALT_MODELS = ("llama-3.3-70b-versatile", "llama-3.1-8b-instant")
_CEREBRAS_ALT_MODELS = ("gpt-oss-120b", "llama-3.3-70b")


def _labeled_keys(prefix: str) -> list[tuple[str, str]]:
    from llm_providers import _slots  # noqa: E402

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for env in (prefix,):
        k = (os.getenv(env, "") or "").strip()
        if k and k not in seen:
            seen.add(k)
            out.append((env, k))
    for i in range(1, _slots() + 1):
        env = f"{prefix}_{i}"
        k = (os.getenv(env, "") or "").strip()
        if k and k not in seen:
            seen.add(k)
            out.append((env, k))
    return out


def _ping(base: str, key: str, model: str) -> tuple[bool, str]:
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
        return True, f"response={snippet!r}"
    except Exception as e:
        if _is_rate_limited(e):
            return True, "rate limited (429 — anahtar geçerli)"
        code = getattr(e, "code", None)
        detail = http_error_detail(e)
        ip_blk = _is_ip_blocked(e)
        hint = ""
        low = detail.lower()
        if ip_blk:
            hint = " → datacenter IP engeli (403 + network settings)"
        elif "decommissioned" in low or "model_decommissioned" in low:
            hint = " → model kapatılmış; .env model adını güncelleyin"
        elif code == 401:
            hint = " → geçersiz API anahtarı"
        elif code == 403:
            hint = " → 403 (otomatik IP block yok — anahtar/plan kontrol)"
        return False, f"HTTP={code} ip_blocked={ip_blk} {detail[:220]}{hint}"


def probe_provider(pid: str) -> None:
    prefix, base, model_env = _OPENAI_PROVIDERS[pid]
    raw_model = (os.getenv(model_env) or _DEFAULT_MODELS.get(pid, "")).strip()
    model = resolve_model(pid, raw_model)
    labeled = _labeled_keys(prefix)
    print(f"\n{'=' * 60}")
    print(f"{pid.upper()} — {len(labeled)} key(s)")
    print(f"  env {model_env}={raw_model!r} → resolved={model!r}")
    print(f"{'=' * 60}")
    if not labeled:
        print("  SKIP: no keys in environment")
        return
    ok = fail = rate = 0
    alts = _GROQ_ALT_MODELS if pid == "groq" else _CEREBRAS_ALT_MODELS
    for i, (name, key) in enumerate(labeled):
        success, msg = _ping(base, key, model)
        if success:
            if "429" in msg or "rate limited" in msg:
                print(f"  429  {name}  {msg}")
                rate += 1
            else:
                print(f"  OK   {name}  model={model}  {msg}")
                ok += 1
            continue
        print(f"  FAIL {name}  model={model}  {msg}")
        fail += 1
        if i == 0:
            for alt in alts:
                if alt == model:
                    continue
                s2, m2 = _ping(base, key, alt)
                tag = "OK" if s2 and "429" not in m2 else ("429" if s2 else "FAIL")
                print(f"       ↳ {tag} alternate model={alt}  {m2}")
                if s2 and tag == "OK":
                    print(f"       ⚠ .env içinde {model_env}={alt} yapın (şu an {raw_model!r})")
                    break
    print(f"  → {ok} OK, {rate} rate-limited, {fail} failed (total {len(labeled)})")


def probe_ollama() -> None:
    import json
    import urllib.request

    url = (os.getenv("OLLAMA_URL", "") or "").strip().rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    print(f"\n{'=' * 60}")
    print(f"OLLAMA — url={url or '(not set)'} model={model}")
    print(f"{'=' * 60}")
    if not url:
        print("  SKIP")
        return
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=15) as resp:
            tags = json.loads(resp.read())
        names = [m.get("name", "") for m in tags.get("models") or []]
        base = model.split(":")[0]
        if not any(base in n for n in names):
            print(f"  ! model not pulled — run: docker compose exec ollama ollama pull {model}")
    except Exception as e:
        print(f"  ! /api/tags: {e}")
    try:
        text = _ollama_chat("Reply with exactly one word: OK", 16, 0)
        print(f"  OK   response={(text or '')[:60]!r}")
    except Exception as e:
        err = str(e)
        if "timed out" in err.lower():
            print(f"  FAIL timeout — CPU'da 8b çok yavaş; .env: OLLAMA_MODEL=llama3.2:3b + fix-ollama-on-server.sh")
        else:
            print(f"  FAIL {e}")


def main() -> None:
    from llm_providers import cloud_bypass_configured, groq_api_base, cerebras_api_base  # noqa: E402

    print("LLM key probe — live API (not .env presence only)")
    print(f"LLM_PROVIDER_ORDER={os.getenv('LLM_PROVIDER_ORDER', '(default)')}")
    print(f"cloud_bypass={cloud_bypass_configured()} groq_base={groq_api_base()}")
    if os.getenv("LLM_RELAY_URL"):
        print(f"LLM_RELAY_URL={os.getenv('LLM_RELAY_URL')}")
    if os.getenv("HTTPS_PROXY") or os.getenv("ALL_PROXY"):
        print("proxy=configured (masked)")
    probe_provider("groq")
    probe_provider("cerebras")
    probe_provider("google")
    probe_ollama()
    print("\nDone.")


if __name__ == "__main__":
    main()
