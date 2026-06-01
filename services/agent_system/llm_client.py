"""
Multi-provider LLM client with automatic fallback.
Tries providers in order: Groq → Cerebras → SambaNova → OpenRouter
On 429 rate limit, automatically moves to the next provider.
"""
import asyncio
import logging
import os

import aiohttp

log = logging.getLogger(__name__)

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
        "model": "llama3.3-70b",
        "headers": {},
    },
    {
        "name": "SambaNova",
        "url": "https://api.sambanova.ai/v1/chat/completions",
        "key_env": "SAMBANOVA_API_KEY",
        "model": "Meta-Llama-3.3-70B-Instruct",
        "headers": {},
    },
    {
        "name": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
        "model": "meta-llama/llama-3.1-8b-instruct:free",
        "headers": {
            "HTTP-Referer": "https://prometheus-trading.io",
            "X-Title": "Prometheus Trading",
        },
    },
]


async def chat_completion(
    prompt: str,
    system: str = "",
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> tuple[str, str]:
    """Try each provider in order. Returns (content, provider_name).
    Raises RuntimeError if all providers fail or are rate-limited."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_error = "tüm sağlayıcılar denendi"

    async with aiohttp.ClientSession() as session:
        for p in _PROVIDERS:
            api_key = os.getenv(p["key_env"], "")
            if not api_key:
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
                        log.warning(f"LLM [{p['name']}] rate limit — sonraki sağlayıcıya geçiliyor")
                        last_error = f"{p['name']} 429"
                        continue
                    if resp.status != 200:
                        body = await resp.text()
                        log.warning(f"LLM [{p['name']}] hata {resp.status} — sonraki sağlayıcıya geçiliyor")
                        last_error = f"{p['name']} {resp.status}: {body[:80]}"
                        continue
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    log.debug(f"LLM [{p['name']}] başarılı")
                    return content, p["name"]
            except asyncio.TimeoutError:
                log.warning(f"LLM [{p['name']}] timeout — sonraki sağlayıcıya geçiliyor")
                last_error = f"{p['name']} timeout"
            except Exception as e:
                log.warning(f"LLM [{p['name']}] bağlantı hatası: {e}")
                last_error = str(e)

    raise RuntimeError(f"Tüm LLM sağlayıcıları başarısız. Son hata: {last_error}")
