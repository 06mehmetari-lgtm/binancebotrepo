"""
Multi-provider LLM client — key rotation + automatic fallback.

Provider sırası: Groq → Cerebras → SambaNova → OpenRouter → Cohere → DeepSeek → Z.AI → Ollama

Her provider için çoklu key desteği:
  GROQ_API_KEY, GROQ_API_KEY_1, GROQ_API_KEY_2, ... GROQ_API_KEY_50
429 gelince o KEY 65s atlanır, aynı provider'ın diğer key'i denenir.
"""
import asyncio
import logging
import os
import time

import aiohttp

log = logging.getLogger(__name__)

OLLAMA_URL    = os.getenv("OLLAMA_URL",   "http://ollama:11434")
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
_active_model = OLLAMA_MODEL  # updated at runtime by ollama_trainer


def set_ollama_model(name: str) -> None:
    global _active_model
    _active_model = name
    log.info(f"Ollama active model → {name}")

# Per-key cooldown: key_prefix → resume_at (float timestamp)
_key_cooldown: dict[str, float] = {}
RATE_LIMIT_COOLDOWN = 65

_ollama_lock: asyncio.Lock | None = None

# Per-provider session stats (in-memory, pushed to Redis by main.py)
_stats: dict[str, dict] = {}


def _stat(provider: str) -> dict:
    return _stats.setdefault(provider, {
        "calls": 0, "rate_limits": 0, "errors": 0,
        "successes": 0, "last_success_ts": 0.0, "last_error": "",
    })


def get_provider_stats() -> dict:
    """Return stats + key readiness for each provider. Called by main.py every 30s."""
    result = {}
    now = time.time()
    for p in _PROVIDERS:
        keys = _collect_keys(p["key_env"])
        ready = sum(1 for k in keys if _is_ready(k))
        # Earliest cooldown expiry among all keys
        cooldown_until = max(
            (_key_cooldown.get(_key_tag(k), 0.0) for k in keys),
            default=0.0,
        )
        s = _stat(p["name"])
        result[p["name"]] = {
            **s,
            "keys_total": len(keys),
            "keys_ready": ready,
            "cooldown_until": cooldown_until if cooldown_until > now else 0.0,
        }
    # Ollama (no API key concept)
    s = _stat("Ollama")
    result["Ollama"] = {**s, "keys_total": 1, "keys_ready": 1, "cooldown_until": 0.0}
    return result


def _get_ollama_lock() -> asyncio.Lock:
    global _ollama_lock
    if _ollama_lock is None:
        _ollama_lock = asyncio.Lock()
    return _ollama_lock


def _collect_keys(base_env: str) -> list[str]:
    """GROQ_API_KEY + GROQ_API_KEY_1 … GROQ_API_KEY_50 → liste"""
    keys: list[str] = []
    base = os.getenv(base_env, "")
    if base:
        keys.append(base)
    for i in range(1, 51):
        k = os.getenv(f"{base_env}_{i}", "")
        if k and k not in keys:
            keys.append(k)
    return keys


def _key_tag(key: str) -> str:
    return key[:12]


def _is_ready(key: str) -> bool:
    return time.time() >= _key_cooldown.get(_key_tag(key), 0)


def _set_cooldown(key: str, seconds: float = RATE_LIMIT_COOLDOWN):
    _key_cooldown[_key_tag(key)] = time.time() + seconds
    log.warning(f"  ↳ key ...{key[-4:]} cooldown {int(seconds)}s")


# ── Provider sırası: hızlı/ücretsiz önce, ücretli sonra, Ollama en sonda ─────
# 400/404 → aynı provider'ın models[] listesindeki sonraki model denenir
# 429 → o key 65s bekleme; aynı provider'ın diğer key'i denenir
# 402/403 → 24 saat bloke
_PROVIDERS = [
    # ── Tier-1: Çok hızlı, çok key, ücretsiz ────────────────────────────────
    {
        "name": "Groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key_env": "GROQ_API_KEY",
        "models": [
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "meta-llama/llama-4-maverick-17b-128e-instruct",
            "llama-3.3-70b-versatile",
            "llama-3.1-70b-versatile",
            "llama-3.1-8b-instant",
            "gemma2-9b-it",
        ],
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "headers": {},
    },
    {
        "name": "Cerebras",
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "key_env": "CEREBRAS_API_KEY",
        "models": [
            "llama-4-scout-17b",
            "llama3.3-70b",
            "llama3.1-70b",
            "llama3.1-8b",
        ],
        "model": "llama3.3-70b",
        "headers": {},
    },
    # ── Tier-2: Ücretsiz/ucuz, iyi kapasite ─────────────────────────────────
    {
        "name": "SambaNova",
        "url": "https://api.sambanova.ai/v1/chat/completions",
        "key_env": "SAMBANOVA_API_KEY",
        "models": [
            "DeepSeek-V3.1",
            "Meta-Llama-3.3-70B-Instruct",
            "Meta-Llama-3.1-405B-Instruct",
            "Meta-Llama-3.1-70B-Instruct",
        ],
        "model": "DeepSeek-V3.1",
        "headers": {},
    },
    {
        "name": "Together",
        "url": "https://api.together.xyz/v1/chat/completions",
        "key_env": "TOGETHER_API_KEY",
        "models": [
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
            "Qwen/Qwen2.5-72B-Instruct-Turbo",
            "mistralai/Mixtral-8x22B-Instruct-v0.1",
            "deepseek-ai/DeepSeek-V3",
        ],
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "headers": {},
    },
    {
        "name": "Fireworks",
        "url": "https://api.fireworks.ai/inference/v1/chat/completions",
        "key_env": "FIREWORKS_API_KEY",
        "models": [
            "accounts/fireworks/models/llama-v3p3-70b-instruct",
            "accounts/fireworks/models/llama-v3p1-70b-instruct",
            "accounts/fireworks/models/deepseek-v3",
            "accounts/fireworks/models/mixtral-8x22b-instruct",
            "accounts/fireworks/models/qwen2p5-72b-instruct",
        ],
        "model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
        "headers": {},
    },
    {
        "name": "Deepinfra",
        "url": "https://api.deepinfra.com/v1/openai/chat/completions",
        "key_env": "DEEPINFRA_API_KEY",
        "models": [
            "meta-llama/Llama-3.3-70B-Instruct",
            "meta-llama/Meta-Llama-3.1-70B-Instruct",
            "Qwen/Qwen2.5-72B-Instruct",
            "deepseek-ai/DeepSeek-V3",
            "mistralai/Mistral-7B-Instruct-v0.3",
            "google/gemma-2-27b-it",
        ],
        "model": "meta-llama/Llama-3.3-70B-Instruct",
        "headers": {},
    },
    {
        "name": "NVIDIA",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "key_env": "NVIDIA_API_KEY",
        "models": [
            "meta/llama-3.3-70b-instruct",
            "meta/llama-3.1-70b-instruct",
            "mistralai/mixtral-8x22b-instruct-v0.1",
            "qwen/qwen2.5-72b-instruct",
            "deepseek-ai/deepseek-v3",
        ],
        "model": "meta/llama-3.3-70b-instruct",
        "headers": {},
    },
    {
        "name": "Mistral",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "key_env": "MISTRAL_API_KEY",
        "models": [
            "mistral-large-latest",
            "mistral-small-latest",
            "open-mistral-nemo",
            "open-mistral-7b",
        ],
        "model": "mistral-small-latest",
        "headers": {},
    },
    {
        "name": "Novita",
        "url": "https://api.novita.ai/v3/openai/chat/completions",
        "key_env": "NOVITA_API_KEY",
        "models": [
            "meta-llama/llama-3.3-70b-instruct",
            "meta-llama/llama-3.1-70b-instruct",
            "qwen/qwen2.5-72b-instruct",
            "deepseek/deepseek-v3",
        ],
        "model": "meta-llama/llama-3.3-70b-instruct",
        "headers": {},
    },
    {
        "name": "Kluster",
        "url": "https://api.kluster.ai/v1/chat/completions",
        "key_env": "KLUSTER_API_KEY",
        "models": [
            "klusterai/Meta-Llama-3.3-70B-Instruct-Turbo",
            "klusterai/Meta-Llama-3.1-405B-Instruct-Turbo",
        ],
        "model": "klusterai/Meta-Llama-3.3-70B-Instruct-Turbo",
        "headers": {},
    },
    # ── Tier-3: Özel modeller / farklı güçlü yönler ─────────────────────────
    {
        "name": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
        "models": [
            "meta-llama/llama-3.3-70b-instruct:free",
            "qwen/qwen-2.5-72b-instruct:free",
            "google/gemma-2-9b-it:free",
            "mistralai/mistral-7b-instruct:free",
            "deepseek/deepseek-v3:free",
        ],
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "headers": {
            "HTTP-Referer": "https://prometheus-trading.io",
            "X-Title": "Prometheus Trading",
        },
    },
    {
        "name": "Perplexity",
        "url": "https://api.perplexity.ai/chat/completions",
        "key_env": "PERPLEXITY_API_KEY",
        "models": [
            "llama-3.1-sonar-large-128k-online",
            "llama-3.1-sonar-small-128k-online",
            "llama-3.1-70b-instruct",
        ],
        "model": "llama-3.1-sonar-large-128k-online",
        "headers": {},
    },
    {
        "name": "XAI",
        "url": "https://api.x.ai/v1/chat/completions",
        "key_env": "XAI_API_KEY",
        "models": ["grok-3-mini-fast", "grok-3-mini", "grok-beta"],
        "model": "grok-3-mini-fast",
        "headers": {},
    },
    {
        "name": "HuggingFace",
        "url": "https://api-inference.huggingface.co/v1/chat/completions",
        "key_env": "HUGGINGFACE_API_KEY",
        "models": [
            "Qwen/Qwen2.5-72B-Instruct",
            "meta-llama/Llama-3.3-70B-Instruct",
            "mistralai/Mistral-7B-Instruct-v0.3",
        ],
        "model": "Qwen/Qwen2.5-72B-Instruct",
        "headers": {},
    },
    {
        "name": "Cohere",
        "url": "https://api.cohere.com/compatibility/v1/chat/completions",
        "key_env": "COHERE_API_KEY",
        "models": ["command-r-plus-08-2024", "command-r-08-2024", "command-light"],
        "model": "command-r-plus-08-2024",
        "headers": {},
    },
    {
        "name": "AI21",
        "url": "https://api.ai21.com/studio/v1/chat/completions",
        "key_env": "AI21_API_KEY",
        "models": ["jamba-1.5-mini", "jamba-1.5-large"],
        "model": "jamba-1.5-mini",
        "headers": {},
    },
    {
        "name": "DeepSeek",
        "url": "https://api.deepseek.com/v1/chat/completions",
        "key_env": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "model": "deepseek-chat",
        "headers": {},
    },
    {
        "name": "ZAI",
        "url": os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4") + "/chat/completions",
        "key_env": "ZAI_API_KEY",
        "models": [os.getenv("ZAI_MODEL", "GLM-4.5"), "GLM-4-Flash", "GLM-4-Air"],
        "model": os.getenv("ZAI_MODEL", "GLM-4.5"),
        "headers": {},
    },
]


async def _ollama_completion(
    messages: list,
    temperature: float,
    max_tokens: int,
    session: aiohttp.ClientSession,
) -> str:
    payload = {
        "model": _active_model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    async with _get_ollama_lock():
        async with session.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=180),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Ollama {resp.status}: {body[:120]}")
            data = await resp.json()
            content = data.get("message", {}).get("content", "")
            if not content:
                raise RuntimeError("Ollama yanıt içeriği boş")
            return content


async def chat_completion(
    prompt: str,
    system: str = "",
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> tuple[str, str]:
    """
    Tüm provider'ları key rotation ile dener.
    Returns (content, provider_name).
    429 → o key 65s atlanır, aynı provider'ın diğer key'i denenir.
    """
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_error = "tüm sağlayıcılar denendi"

    async with aiohttp.ClientSession() as session:
        for p in _PROVIDERS:
            keys = _collect_keys(p["key_env"])
            if not keys:
                continue

            provider_models = p.get("models", [p["model"]])
            for api_key in keys:
                if not _is_ready(api_key):
                    continue

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    **p["headers"],
                }
                _stat(p["name"])["calls"] += 1

                model_succeeded = False
                for model_name in provider_models:
                    payload = {
                        "model": model_name,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    try:
                        async with session.post(
                            p["url"], headers=headers, json=payload,
                            timeout=aiohttp.ClientTimeout(total=30),
                        ) as resp:
                            if resp.status == 429:
                                log.warning(f"LLM [{p['name']}] 429 rate limit")
                                _set_cooldown(api_key)
                                _stat(p["name"])["rate_limits"] += 1
                                break  # rate limited — try next key
                            if resp.status in (402, 403):
                                body = await resp.text()
                                log.warning(f"LLM [{p['name']}] {resp.status} bakiye/erişim sorunu — 24h bloke")
                                last_error = f"{p['name']} {resp.status}"
                                _stat(p["name"])["errors"] += 1
                                _stat(p["name"])["last_error"] = f"HTTP {resp.status}"
                                _set_cooldown(api_key, seconds=86400)
                                break
                            if resp.status in (400, 404):
                                body = await resp.text()
                                log.warning(f"LLM [{p['name']}] {resp.status} model={model_name} — sonraki modele geçiliyor")
                                last_error = f"{p['name']} {resp.status} ({model_name})"
                                _stat(p["name"])["errors"] += 1
                                _stat(p["name"])["last_error"] = f"HTTP {resp.status} {model_name}"
                                continue  # try next model in list
                            if resp.status != 200:
                                body = await resp.text()
                                log.warning(f"LLM [{p['name']}] {resp.status}: {body[:80]}")
                                last_error = f"{p['name']} {resp.status}"
                                _stat(p["name"])["errors"] += 1
                                _stat(p["name"])["last_error"] = last_error
                                break  # unknown error — skip this provider
                            data = await resp.json()
                            content = data["choices"][0]["message"]["content"]
                            if not content:
                                last_error = f"{p['name']} boş yanıt"
                                continue
                            log.debug(f"LLM [{p['name']}] model={model_name} ...{api_key[-4:]} başarılı")
                            _stat(p["name"])["successes"] += 1
                            _stat(p["name"])["last_success_ts"] = time.time()
                            return content, p["name"]
                    except asyncio.TimeoutError:
                        log.warning(f"LLM [{p['name']}] timeout")
                        last_error = f"{p['name']} timeout"
                        _stat(p["name"])["errors"] += 1
                        _stat(p["name"])["last_error"] = "timeout"
                        break
                    except Exception as e:
                        log.warning(f"LLM [{p['name']}] bağlantı hatası: {e}")
                        last_error = str(e)
                        _stat(p["name"])["errors"] += 1
                        _stat(p["name"])["last_error"] = str(e)[:80]
                        break

        # Ollama — yerel yedek, sıralı (lock ile)
        try:
            log.info("LLM [Ollama] tüm cloud sağlayıcılar başarısız — yerel modele geçiliyor")
            _stat("Ollama")["calls"] += 1
            content = await _ollama_completion(messages, temperature, max_tokens, session)
            log.info("LLM [Ollama] başarılı")
            _stat("Ollama")["successes"] += 1
            _stat("Ollama")["last_success_ts"] = time.time()
            return content, "Ollama"
        except Exception as e:
            log.error(f"LLM [Ollama] hata: {e}")
            _stat("Ollama")["errors"] += 1
            _stat("Ollama")["last_error"] = str(e)[:80]
            last_error = f"Ollama: {e}"

    raise RuntimeError(f"Tüm LLM sağlayıcıları başarısız. Son hata: {last_error}")
