"""
Multi-provider LLM client with automatic fallback.
Order: Groq → Cerebras → SambaNova → OpenRouter → Ollama (local, unlimited)
On 429 / error, automatically moves to the next provider.
Ollama is always last — no API key required, no rate limits.
"""
import asyncio
import logging
import os
import time

import aiohttp

log = logging.getLogger(__name__)

OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

_PROVIDERS = [
    {
        "name": "Groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key_env": "GROQ_API_KEY",
        "model": "llama-3.3-70b-versatile",
        "headers": {},
    },
    {
        "name": "Cerebras",
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "key_env": "CEREBRAS_API_KEY",
        "model": "llama3.1-8b",
        "headers": {},
    },
    {
        "name": "SambaNova",
        "url": "https://api.sambanova.ai/v1/chat/completions",
        "key_env": "SAMBANOVA_API_KEY",
        "model": "Meta-Llama-3.1-8B-Instruct",
        "headers": {},
    },
    {
        "name": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
        "model": "google/gemma-2-9b-it:free",
        "headers": {
            "HTTP-Referer": "https://prometheus-trading.io",
            "X-Title": "Prometheus Trading",
        },
    },
]

# Per-provider rate limit cooldown: provider_name → resume_at timestamp
_provider_cooldown: dict[str, float] = {}
RATE_LIMIT_COOLDOWN = 65  # saniye — Groq/SambaNova penceresi 60s

# Ollama'ya aynı anda tek istek (local model, sıralı çalışır)
_ollama_lock: asyncio.Lock | None = None


def _get_ollama_lock() -> asyncio.Lock:
    global _ollama_lock
    if _ollama_lock is None:
        _ollama_lock = asyncio.Lock()
    return _ollama_lock


async def _ollama_completion(
    messages: list,
    temperature: float,
    max_tokens: int,
    session: aiohttp.ClientSession,
) -> str:
    """Call local Ollama — no rate limits, always available."""
    payload = {
        "model": OLLAMA_MODEL,
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
    """Try each provider in order. Returns (content, provider_name).
    Falls back to local Ollama if all cloud providers fail.
    Rate-limited providers are skipped for 65 seconds after a 429."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    now = time.time()
    last_error = "tüm sağlayıcılar denendi"

    async with aiohttp.ClientSession() as session:
        # Cloud providers first
        for p in _PROVIDERS:
            api_key = os.getenv(p["key_env"], "")
            if not api_key:
                continue

            # Skip if this provider hit a rate limit recently
            resume_at = _provider_cooldown.get(p["name"], 0)
            if now < resume_at:
                remaining = int(resume_at - now)
                log.debug(f"LLM [{p['name']}] cooldown — {remaining}s kaldı, atlanıyor")
                continue

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                **p["headers"],
            }
            payload = {
                "model": p["model"],
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            try:
                async with session.post(
                    p["url"], headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=90),
                ) as resp:
                    if resp.status == 429:
                        _provider_cooldown[p["name"]] = time.time() + RATE_LIMIT_COOLDOWN
                        log.warning(f"LLM [{p['name']}] rate limit — {RATE_LIMIT_COOLDOWN}s cooldown")
                        last_error = f"{p['name']} 429"
                        continue
                    if resp.status != 200:
                        body = await resp.text()
                        log.warning(f"LLM [{p['name']}] hata {resp.status} — sonraki sağlayıcıya geçiliyor")
                        last_error = f"{p['name']} {resp.status}: {body[:80]}"
                        continue
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    if not content:
                        last_error = f"{p['name']} boş yanıt"
                        continue
                    log.debug(f"LLM [{p['name']}] başarılı")
                    return content, p["name"]
            except asyncio.TimeoutError:
                log.warning(f"LLM [{p['name']}] timeout — sonraki sağlayıcıya geçiliyor")
                last_error = f"{p['name']} timeout"
            except Exception as e:
                log.warning(f"LLM [{p['name']}] bağlantı hatası: {e}")
                last_error = str(e)

        # Ollama — local fallback, queued (one at a time to avoid overload)
        try:
            log.info("LLM [Ollama] tüm bulut sağlayıcılar başarısız — yerel modele geçiliyor")
            content = await _ollama_completion(messages, temperature, max_tokens, session)
            log.info("LLM [Ollama] başarılı")
            return content, "Ollama"
        except Exception as e:
            log.error(f"LLM [Ollama] hata: {e}")
            last_error = f"Ollama: {e}"

    raise RuntimeError(f"Tüm LLM sağlayıcıları başarısız. Son hata: {last_error}")
