"""Live LLM provider health probes — Groq/Cerebras 403 detection for dashboard."""

from __future__ import annotations

import json
import os
import time
import urllib.request

REDIS_KEY = "system:llm:health"


def _probe_openai(pid: str) -> dict:
    from llm_providers import (
        _DEFAULT_MODELS,
        _OPENAI_PROVIDERS,
        _is_ip_blocked,
        _is_rate_limited,
        _openai_chat,
        collect_keys,
        http_error_detail,
        resolve_model,
    )

    if pid not in _OPENAI_PROVIDERS:
        return {"id": pid, "status": "unknown", "ok": False, "http_code": None, "message": "", "ip_blocked": False}

    prefix, base, model_env = _OPENAI_PROVIDERS[pid]
    keys = collect_keys(prefix)
    if pid == "google":
        from llm_providers import collect_keys as ck

        keys = ck("GOOGLE_AI_API_KEY", "GEMINI_API_KEY") or keys

    if not keys:
        return {
            "id": pid,
            "status": "no_keys",
            "ok": False,
            "http_code": None,
            "message": "Anahtar tanımlı değil",
            "ip_blocked": False,
        }

    model = resolve_model(pid, os.getenv(model_env, _DEFAULT_MODELS.get(pid, "")))
    try:
        text = _openai_chat(
            base_url=base,
            api_key=keys[0],
            model=model,
            prompt="Reply with exactly one word: OK",
            max_tokens=8,
            temperature=0,
        )
        return {
            "id": pid,
            "status": "ok",
            "ok": True,
            "http_code": 200,
            "message": f"Yanıt: {(text or '')[:40]}",
            "ip_blocked": False,
            "key_source": "runtime" if _runtime_active(pid) else "env",
        }
    except Exception as e:
        if _is_rate_limited(e):
            return {
                "id": pid,
                "status": "ok",
                "ok": True,
                "http_code": 429,
                "message": "Rate limit — anahtar geçerli",
                "ip_blocked": False,
                "key_source": "runtime" if _runtime_active(pid) else "env",
            }
        code = getattr(e, "code", None)
        detail = http_error_detail(e)[:220]
        ip_blocked = _is_ip_blocked(e) or code == 403
        return {
            "id": pid,
            "status": "blocked" if code == 403 else "error",
            "ok": False,
            "http_code": code,
            "message": detail,
            "ip_blocked": ip_blocked,
            "key_source": "runtime" if _runtime_active(pid) else "env",
        }


def _runtime_active(pid: str) -> bool:
    try:
        from llm_runtime_keys import get_runtime_keys

        return bool(get_runtime_keys(pid))
    except ImportError:
        return False


def _probe_ollama() -> dict:
    url = (os.getenv("OLLAMA_URL", "") or "").strip().rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    if not url:
        return {"id": "ollama", "status": "no_url", "ok": False, "message": "OLLAMA_URL yok"}
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=8) as resp:
            tags = json.loads(resp.read())
        names = [m.get("name", "") for m in tags.get("models") or []]
        base = model.split(":")[0]
        has_model = any(base in n for n in names)
        return {
            "id": "ollama",
            "status": "ok" if has_model else "no_model",
            "ok": has_model,
            "message": f"{len(names)} model" if has_model else f"Model yok — ollama pull {model}",
            "models": names[:8],
        }
    except Exception as e:
        return {"id": "ollama", "status": "error", "ok": False, "message": str(e)[:180]}


def build_health_payload() -> dict:
    groq = _probe_openai("groq")
    cerebras = _probe_openai("cerebras")
    google = _probe_openai("google")
    ollama = _probe_ollama()

    groq_blocked = groq.get("status") == "blocked" or groq.get("ip_blocked")
    cerebras_blocked = cerebras.get("status") == "blocked" or cerebras.get("ip_blocked")
    any_cloud_ok = bool(groq.get("ok") or cerebras.get("ok") or google.get("ok"))
    needs_key_update = bool(
        (groq_blocked or cerebras_blocked)
        and groq.get("status") != "no_keys"
        and not any_cloud_ok
    )

    if groq_blocked and cerebras_blocked and not any_cloud_ok and not ollama.get("ok"):
        alert_level = "critical"
        alert_message = (
            "Groq ve Cerebras bu sunucudan 403 (VPS IP engeli). "
            "Yeni anahtar deneyin veya Google Gemini / Ollama kullanın."
        )
    elif needs_key_update:
        alert_level = "warning"
        alert_message = "Bulut LLM erişim sorunu — anahtarları güncelleyin veya alternatif sağlayıcı ekleyin."
    elif not any_cloud_ok and not ollama.get("ok"):
        alert_level = "warning"
        alert_message = "Hiçbir LLM sağlayıcısı yanıt vermiyor."
    else:
        alert_level = "ok"
        alert_message = ""

    try:
        from llm_runtime_keys import runtime_keys_active

        runtime_active = runtime_keys_active()
    except ImportError:
        runtime_active = False

    return {
        "updated_at": time.time(),
        "providers": {
            "groq": groq,
            "cerebras": cerebras,
            "google": google,
            "ollama": ollama,
        },
        "any_cloud_ok": any_cloud_ok,
        "cloud_blocked": groq_blocked and cerebras_blocked,
        "needs_key_update": needs_key_update,
        "alert_level": alert_level,
        "alert_message": alert_message,
        "runtime_keys_active": runtime_active,
    }
