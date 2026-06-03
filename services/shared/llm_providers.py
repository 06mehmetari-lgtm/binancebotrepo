"""
Multi-provider LLM with key rotation and fallback chain.
Reads GROQ_API_KEY + GROQ_API_KEY_1..N (LLM_KEY_SLOTS), then providers in LLM_PROVIDER_ORDER.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_ORDER = (
    "ollama,groq,cerebras,sambanova,openrouter,mistral,together,fireworks,"
    "cohere,deepseek,huggingface,google,perplexity,zai,anthropic"
)

_cloud_ip_blocked: bool = False

_OPENAI_PROVIDERS: dict[str, tuple[str, str, str]] = {
    # id -> (key_prefix, base_url, model_env)
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "GROQ_LEARN_MODEL"),
    "cerebras": ("CEREBRAS_API_KEY", "https://api.cerebras.ai/v1", "CEREBRAS_MODEL"),
    "sambanova": ("SAMBANOVA_API_KEY", "https://api.sambanova.ai/v1", "SAMBANOVA_MODEL"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "OPENROUTER_MODEL"),
    "mistral": ("MISTRAL_API_KEY", "https://api.mistral.ai/v1", "MISTRAL_MODEL"),
    "together": ("TOGETHER_API_KEY", "https://api.together.xyz/v1", "TOGETHER_MODEL"),
    "fireworks": ("FIREWORKS_API_KEY", "https://api.fireworks.ai/inference/v1", "FIREWORKS_MODEL"),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com", "DEEPSEEK_MODEL"),
    "google": ("GOOGLE_AI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai", "GOOGLE_AI_MODEL"),
    "perplexity": ("PERPLEXITY_API_KEY", "https://api.perplexity.ai", "PERPLEXITY_MODEL"),
    "zai": ("ZAI_API_KEY", "https://api.z.ai/api/paas/v4", "ZAI_MODEL"),
}

# Deprecated provider model IDs → current replacements (see Groq/Cerebras deprecation docs)
_MODEL_REMAP: dict[str, dict[str, str]] = {
    "groq": {
        "llama-3.1-70b-versatile": "llama-3.3-70b-versatile",
        "llama-3.1-70b-specdec": "llama-3.3-70b-specdec",
        "mixtral-8x7b-32768": "llama-3.3-70b-versatile",
        "gemma2-9b-it": "llama-3.1-8b-instant",
        "llama3-70b-8192": "llama-3.3-70b-versatile",
        "llama3-8b-8192": "llama-3.1-8b-instant",
    },
    "cerebras": {
        "llama3.1-8b": "gpt-oss-120b",
        "llama3.1-70b": "llama-3.3-70b",
    },
}

_DEFAULT_MODELS: dict[str, str] = {
    "groq": "llama-3.3-70b-versatile",
    "cerebras": "gpt-oss-120b",
    "sambanova": "Meta-Llama-3.1-8B-Instruct",
    "openrouter": "google/gemma-2-9b-it:free",
    "mistral": "open-mistral-nemo",
    "together": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
    "fireworks": "accounts/fireworks/models/llama-v3p1-8b-instruct",
    "deepseek": "deepseek-chat",
    "google": "gemini-2.0-flash",
    "perplexity": "sonar",
    "zai": "glm-4-flash",
}


def _slots() -> int:
    try:
        return max(1, min(64, int(os.getenv("LLM_KEY_SLOTS", "32"))))
    except ValueError:
        return 32


def collect_keys(prefix: str, alt_primary: str | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for env in (alt_primary or prefix,):
        k = (os.getenv(env, "") or "").strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    for i in range(1, _slots() + 1):
        k = (os.getenv(f"{prefix}_{i}", "") or "").strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def vps_llm_mode() -> bool:
    """PC kapalı VPS: sadece Google Gemini + Ollama (Groq/Cerebras 1010 atlanır)."""
    return (os.getenv("LLM_VPS_MODE", "") or "").strip().lower() in ("1", "true", "yes", "on")


def provider_order() -> list[str]:
    if vps_llm_mode():
        out = ["google", "ollama"]
        if collect_keys("GOOGLE_AI_API_KEY", "GEMINI_API_KEY"):
            return out
        return ["ollama"]
    raw = os.getenv("LLM_PROVIDER_ORDER", DEFAULT_ORDER)
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _quota_wait(provider: str) -> None:
    try:
        sec = float(os.getenv("LLM_QUOTA_WAIT_SEC", "0"))
    except ValueError:
        sec = 0.0
    if sec > 0:
        wait = min(sec, 120.0)
        logger.info("%s kota/limit — %.0fs bekleniyor, sonra Ollama/yedek", provider, wait)
        time.sleep(wait)


def resolve_model(provider_id: str, model: str) -> str:
    """Map deprecated model env values to supported IDs."""
    m = (model or "").strip()
    if not m:
        return _DEFAULT_MODELS.get(provider_id, m)
    return _MODEL_REMAP.get(provider_id, {}).get(m, m)


def http_error_detail(exc: BaseException, max_len: int = 280) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            raw = exc.read().decode("utf-8", errors="replace")
            if raw:
                return raw[:max_len]
        except Exception:
            pass
        return f"HTTP {exc.code}: {exc.reason}"
    return str(exc)[:max_len]


def _is_rate_limited(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
        return True
    msg = str(exc).lower()
    return any(x in msg for x in ("429", "rate", "quota", "limit", "too many"))


def _is_ip_blocked(exc: BaseException) -> bool:
    global _cloud_ip_blocked
    if isinstance(exc, urllib.error.HTTPError) and exc.code in (403, 502):
        msg = http_error_detail(exc).lower()
        if any(x in msg for x in ("1010", "access denied", "network settings", "cloudflare")):
            _cloud_ip_blocked = True
            return True
    s = str(exc).lower()
    if "error code: 1010" in s or "access denied" in s:
        _cloud_ip_blocked = True
        return True
    return False


def cloud_bypass_configured() -> bool:
    """Proxy, SOCKS, or LLM relay → Groq/Cerebras can work from blocked VPS."""
    try:
        import proxy_pool as pp

        if pp.proxy_urls() or pp.relay_urls():
            return True
    except ImportError:
        pass
    if (os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY") or "").strip():
        return True
    if (os.getenv("LLM_RELAY_URL") or "").strip():
        return True
    if (os.getenv("GROQ_API_BASE") or os.getenv("CEREBRAS_API_BASE") or "").strip():
        return True
    return False


def cloud_llm_disabled() -> bool:
    """VPS IP block (1010) or operator chose local-only LLM."""
    if cloud_bypass_configured():
        return False
    if _cloud_ip_blocked:
        return True
    v = (os.getenv("LLM_OLLAMA_ONLY", "") or os.getenv("LLM_CLOUD_BLOCKED", "")).strip().lower()
    return v in ("1", "true", "yes", "on")


def groq_api_base() -> str:
    try:
        import proxy_pool as pp

        relays = pp.relay_bases_for("groq")
        if relays:
            return relays[0]
    except ImportError:
        pass
    relay = (os.getenv("LLM_RELAY_URL") or "").strip().rstrip("/")
    if relay:
        return f"{relay}/groq/v1"
    return (os.getenv("GROQ_API_BASE") or "https://api.groq.com/openai/v1").strip().rstrip("/")


def cerebras_api_base() -> str:
    try:
        import proxy_pool as pp

        relays = pp.relay_bases_for("cerebras")
        if relays:
            return relays[0]
    except ImportError:
        pass
    relay = (os.getenv("LLM_RELAY_URL") or "").strip().rstrip("/")
    if relay:
        return f"{relay}/cerebras/v1"
    return (os.getenv("CEREBRAS_API_BASE") or "https://api.cerebras.ai/v1").strip().rstrip("/")


def _provider_base_candidates(pid: str, default: str) -> list[str]:
    try:
        import proxy_pool as pp

        if pid in ("groq", "cerebras"):
            relays = pp.relay_bases_for(pid)
            if relays:
                return relays
    except ImportError:
        pass
    if pid == "groq":
        return [groq_api_base()]
    if pid == "cerebras":
        return [cerebras_api_base()]
    return [default]


def _urlopen_one(req: urllib.request.Request, timeout: float, proxy: str | None):
    if not proxy:
        return urllib.request.urlopen(req, timeout=timeout)
    if proxy.lower().startswith("socks"):
        import socks  # type: ignore[import-untyped]
        from urllib.parse import urlparse

        p = urlparse(proxy)
        host = p.hostname or "127.0.0.1"
        port = p.port or 1080
        scheme = (p.scheme or "socks5").lower()
        kind = socks.SOCKS5 if "5" in scheme else socks.SOCKS4
        socks.set_default_proxy(kind, host, port)
        import socket

        socket.socket = socks.socksocket  # type: ignore[misc, assignment]
        return urllib.request.urlopen(req, timeout=timeout)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    return opener.open(req, timeout=timeout)


def _urlopen(req: urllib.request.Request, timeout: float):
    try:
        import proxy_pool as pp

        attempts = pp.all_proxy_attempts()
    except ImportError:
        attempts = [
            (
                os.getenv("HTTPS_PROXY")
                or os.getenv("HTTP_PROXY")
                or os.getenv("ALL_PROXY")
                or None
            )
        ]
    last: BaseException | None = None
    for proxy in attempts:
        try:
            return _urlopen_one(req, timeout, proxy)
        except Exception as e:
            last = e
            if proxy:
                try:
                    import proxy_pool as pp

                    pp.mark_proxy_bad(proxy)
                    logger.warning("proxy failed, next: %s — %s", proxy[:40], e)
                except ImportError:
                    pass
            elif _is_ip_blocked(e):
                break
            continue
    if last:
        raise last
    raise RuntimeError("no proxy attempts")


def _openai_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    extra_headers: dict[str, str] | None = None,
) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with _urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
        return (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    except Exception as e:
        if _is_ip_blocked(e):
            logger.warning("cloud LLM IP blocked (403/1010) — use Ollama or HTTPS_PROXY")
        raise


def _ollama_chat(prompt: str, max_tokens: int, temperature: float) -> str:
    base = (os.getenv("OLLAMA_URL", "") or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("OLLAMA_URL not set")
    model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
    ).encode()
    req = urllib.request.Request(
        f"{base}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        timeout = float(os.getenv("OLLAMA_TIMEOUT", "180"))
    except ValueError:
        timeout = 180.0
    with _urlopen(req, timeout=max(30.0, timeout)) as resp:
        body = json.loads(resp.read())
    return body.get("message", {}).get("content") or ""


def _try_ollama(prompt: str, max_tokens: int, temperature: float) -> tuple[str | None, str | None]:
    try:
        text = _ollama_chat(prompt, max_tokens, temperature)
        if text.strip():
            return text, "ollama"
    except Exception as e:
        logger.warning("ollama: %s", e)
    return None, None


def _cohere_chat(api_key: str, model: str, prompt: str, max_tokens: int, temperature: float) -> str:
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.cohere.com/v2/chat",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read())
    content = (body.get("message") or {}).get("content") or []
    if content and isinstance(content[0], dict):
        return content[0].get("text") or ""
    return ""


def _hf_chat(api_key: str, model: str, prompt: str, max_tokens: int, temperature: float) -> str:
    return _openai_chat(
        base_url="https://router.huggingface.co/v1",
        api_key=api_key,
        model=model,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _anthropic_chat(api_key: str, model: str, prompt: str, max_tokens: int, temperature: float) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(getattr(b, "text", "") for b in msg.content)


def _model_for(pid: str, model_env: str, override: str | None) -> str:
    if override:
        return resolve_model(pid, override)
    return resolve_model(pid, os.getenv(model_env, _DEFAULT_MODELS.get(pid, "gpt-4o-mini")))


def _try_openai_provider(
    pid: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    model_override: str | None,
) -> tuple[str | None, str | None]:
    prefix, default_base, model_env = _OPENAI_PROVIDERS[pid]
    bases = _provider_base_candidates(pid, default_base)
    if pid == "zai":
        bases = [os.getenv("ZAI_BASE_URL", bases[0])]
    relay_secret = (os.getenv("LLM_RELAY_SECRET") or "").strip()
    keys = collect_keys(prefix)
    if pid == "google":
        keys = collect_keys("GOOGLE_AI_API_KEY", "GEMINI_API_KEY") or keys
    if not keys:
        return None, None
    model = _model_for(pid, model_env, model_override)
    extra = None
    if pid == "openrouter":
        extra = {
            "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "https://prometheus.local"),
            "X-Title": "Prometheus Trading",
        }
    if relay_secret:
        extra = dict(extra or {})
        extra["X-Relay-Secret"] = relay_secret
    for base in bases:
        for idx, key in enumerate(keys):
            label = pid if len(keys) == 1 else f"{pid}#{idx + 1}"
            if len(bases) > 1:
                label = f"{label}@{base.split('/')[2][:20]}"
            try:
                text = _openai_chat(
                    base_url=base,
                    api_key=key,
                    model=model,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    extra_headers=extra,
                )
                if text.strip():
                    return text, label
            except Exception as e:
                if _is_rate_limited(e):
                    _quota_wait(pid)
                    continue
                if _is_ip_blocked(e):
                    try:
                        import proxy_pool as pp

                        for r in pp.relay_urls():
                            if r.rstrip("/") in base:
                                pp.mark_relay_bad(r)
                    except ImportError:
                        pass
                    continue
                logger.debug("%s: %s", label, e)
    return None, None


def chat_completion(
    prompt: str,
    *,
    max_tokens: int = 280,
    temperature: float = 0.35,
    model_override: str | None = None,
    model_pool: str | None = None,
    use_swarm: bool = False,
) -> tuple[str | None, str | None]:
    """
    Returns (raw_text, provider_label) or (None, None).
    model_pool: groq pool id (fast|main|reason|risk|learning|final|vision|fallback).
    use_swarm: parallel multi-model consensus (debate JSON).
    """
    order = provider_order()
    ollama_first = bool(order) and order[0] == "ollama"
    bypass = cloud_bypass_configured()

    # Blocked VPS without bypass: Ollama first
    if (ollama_first or cloud_llm_disabled()) and not bypass:
        text, label = _try_ollama(prompt, max_tokens, temperature)
        if text:
            return text, label

    if not vps_llm_mode() and not cloud_llm_disabled() and model_pool and collect_keys("GROQ_API_KEY"):
        try:
            import groq_orchestrator as groq

            if use_swarm and groq._bool_env("AI_ENABLE_SWARM", True):
                text, label = groq.swarm_consensus(
                    model_pool, prompt, max_tokens=max_tokens, temperature=temperature
                )
                if text:
                    return text, label
            text, label = groq.chat_pool(
                model_pool, prompt, max_tokens=max_tokens, temperature=temperature
            )
            if text:
                return text, label
        except Exception as e:
            if _is_ip_blocked(e):
                text, label = _try_ollama(prompt, max_tokens, temperature)
                if text:
                    return text, label
            logger.debug("groq pool %s: %s", model_pool, e)

    for pid in order:
        if pid == "ollama":
            if (ollama_first or cloud_llm_disabled()) and not bypass:
                continue
            text, label = _try_ollama(prompt, max_tokens, temperature)
            if text:
                return text, label
            continue

        if pid in _OPENAI_PROVIDERS:
            text, label = _try_openai_provider(pid, prompt, max_tokens, temperature, model_override)
            if text:
                return text, label
            if cloud_llm_disabled():
                text, label = _try_ollama(prompt, max_tokens, temperature)
                if text:
                    return text, label
            continue

        if pid == "cohere":
            keys = collect_keys("COHERE_API_KEY")
            model = model_override or os.getenv("COHERE_MODEL", "command-r7b-12-2024")
            for idx, key in enumerate(keys):
                label = "cohere" if len(keys) == 1 else f"cohere#{idx + 1}"
                try:
                    text = _cohere_chat(key, model, prompt, max_tokens, temperature)
                    if text.strip():
                        return text, label
                except Exception as e:
                    if _is_rate_limited(e):
                        continue
                    logger.debug("%s: %s", label, e)
            continue

        if pid == "huggingface":
            keys = collect_keys("HUGGINGFACE_API_KEY", "HF_API_KEY")
            model = model_override or os.getenv("HUGGINGFACE_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")
            for idx, key in enumerate(keys):
                label = "huggingface" if len(keys) == 1 else f"huggingface#{idx + 1}"
                try:
                    text = _hf_chat(key, model, prompt, max_tokens, temperature)
                    if text.strip():
                        return text, label
                except Exception as e:
                    if _is_rate_limited(e):
                        continue
                    logger.debug("%s: %s", label, e)
            continue

        if pid == "anthropic":
            key = (os.getenv("ANTHROPIC_API_KEY", "") or "").strip()
            if not key:
                continue
            model = model_override or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
            try:
                text = _anthropic_chat(key, model, prompt, max_tokens, temperature)
                if text.strip():
                    return text, "anthropic"
            except Exception as e:
                logger.debug("anthropic: %s", e)

    return None, None


def any_cloud_llm_configured() -> bool:
    if collect_keys("GROQ_API_KEY"):
        return True
    for pid, (prefix, _, _) in _OPENAI_PROVIDERS.items():
        if pid != "groq" and collect_keys(prefix):
            return True
    if (os.getenv("COHERE_API_KEY", "") or "").strip():
        return True
    if collect_keys("HUGGINGFACE_API_KEY", "HF_API_KEY"):
        return True
    if (os.getenv("ANTHROPIC_API_KEY", "") or "").strip():
        return True
    return bool((os.getenv("OLLAMA_URL", "") or "").strip())


def status_snapshot() -> list[dict]:
    catalog = [
        ("groq", "GROQ_API_KEY", "~14.400 istek/gün (ücretsiz, anahtar başı)"),
        ("cerebras", "CEREBRAS_API_KEY", "Ücretsiz; dakika limiti (CEREBRAS_API_KEY_1..N)"),
        ("sambanova", "SAMBANOVA_API_KEY", "Ücretsiz tahmini ~600 istek/gün"),
        ("openrouter", "OPENROUTER_API_KEY", "Ücretsiz modeller ~200 istek/gün"),
        ("mistral", "MISTRAL_API_KEY", "Deneme kredisi"),
        ("together", "TOGETHER_API_KEY", "Ücretsiz kredi (kampanyaya göre)"),
        ("fireworks", "FIREWORKS_API_KEY", "Deneme kredisi"),
        ("cohere", "COHERE_API_KEY", "Deneme ~1.000 istek/ay"),
        ("deepseek", "DEEPSEEK_API_KEY", "Token başı ücret"),
        ("huggingface", "HUGGINGFACE_API_KEY", "Ücretsiz; dakika limiti"),
        ("google", "GOOGLE_AI_API_KEY", "Gemini ücretsiz katman"),
        ("perplexity", "PERPLEXITY_API_KEY", "Sonar API"),
        ("zai", "ZAI_API_KEY", "Plana göre"),
        ("anthropic", "ANTHROPIC_API_KEY", "Token başı (9 resmi ajan)"),
        ("ollama", "OLLAMA_URL", "Yerel, sınırsız (GPU/RAM)"),
    ]
    out = []
    for pid, env_hint, tier in catalog:
        if pid == "ollama":
            ok = bool((os.getenv("OLLAMA_URL", "") or "").strip())
            count = 1 if ok else 0
        elif pid == "anthropic":
            count = 1 if (os.getenv("ANTHROPIC_API_KEY", "") or "").strip() else 0
            ok = count > 0
        elif pid == "google":
            keys = collect_keys("GOOGLE_AI_API_KEY", "GEMINI_API_KEY")
            count = len(keys)
            ok = count > 0
        elif pid == "huggingface":
            keys = collect_keys("HUGGINGFACE_API_KEY", "HF_API_KEY")
            count = len(keys)
            ok = count > 0
        else:
            keys = collect_keys(env_hint)
            count = len(keys)
            ok = count > 0
        out.append(
            {
                "id": pid,
                "env": env_hint,
                "configured": ok,
                "key_count": count,
                "tier_note": tier,
            }
        )
    return out
