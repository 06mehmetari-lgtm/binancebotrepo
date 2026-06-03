"""
Multi-LLM Trade Analysis — her trade kapandığında TÜM sağlayıcıları çağırır.

Her LLM şunları analiz eder:
- Coin neden düştü / yükseldi?
- Hangi göstergeler sinyal verdi?
- Düşerken nasıl kazanılırdı?
- Bir dahaki benzer durumda ne yapılmalı?

Tüm analizler training:lessons'a kaydedilir → Ollama ve cloud LLM'lere öğretilir.
"""
import asyncio
import json
import logging
import time
import os

import aiohttp
import redis.asyncio as aioredis

log = logging.getLogger(__name__)

OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://ollama:11434")
REDIS_URL    = os.getenv("REDIS_URL", "redis://redis:6379")


def _build_prompt(trade: dict, features: dict | None) -> str:
    symbol    = trade.get("symbol", "?")
    direction = trade.get("direction", "?").upper()
    pnl_pct   = float(trade.get("pnl_pct", 0))
    regime    = trade.get("regime", trade.get("context_regime", "?"))
    outcome   = "KAZANÇ" if pnl_pct > 0 else "KAYIP"

    rsi  = round(float(features["rsi_14"]), 1)  if features and features.get("rsi_14")   else "?"
    macd = round(float(features["macd_hist"]), 4) if features and features.get("macd_hist") else "?"
    fund = f'{round(float(features["funding_rate"])*100, 4)}%' if features and features.get("funding_rate") else "?"
    vix  = round(float(features["vix_level"]), 1)  if features and features.get("vix_level") else "?"
    vol  = round(float(features["volume_ratio"]), 2) if features and features.get("volume_ratio") else "?"

    return f"""Kripto para trade analizi yap. Bu bir eğitim dersidir.

Sembol: {symbol}
Yön: {direction} | Sonuç: {outcome} ({pnl_pct:+.2f}%) | Rejim: {regime}
RSI: {rsi} | MACD: {macd} | Fonlama: {fund} | VIX: {vix} | Hacim: {vol}x

3 kısa cümle yaz (Türkçe):
1. Bu trade neden {outcome.lower()} ile sonuçlandı?
2. Düşerken SHORT ile nasıl kazanılırdı? (direkt tavsiye ver)
3. Bir dahaki benzer durumda sistem ne yapmalı?"""


async def _call_ollama(prompt: str, session: aiohttp.ClientSession) -> str | None:
    try:
        async with session.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 200},
            },
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("message", {}).get("content", "")
    except Exception as e:
        log.debug(f"Multi-LLM Ollama: {e}")
    return None


async def _call_openai_compat(
    url: str,
    api_key: str,
    model: str,
    prompt: str,
    extra_headers: dict,
    session: aiohttp.ClientSession,
) -> str | None:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **extra_headers,
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 200,
    }
    try:
        async with session.post(
            url, headers=headers, json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        log.debug(f"Multi-LLM {url}: {e}")
    return None


def _get_providers() -> list[dict]:
    """Return all configured providers with a key present in env."""
    providers = []

    def add(name, url, key_env, model, extra=None):
        key = os.getenv(key_env, "")
        if key:
            providers.append({"name": name, "url": url, "key": key, "model": model, "extra": extra or {}})

    _OR = {"HTTP-Referer": "https://prometheus-trading.io", "X-Title": "Prometheus"}
    add("Groq",        "https://api.groq.com/openai/v1/chat/completions",                   "GROQ_API_KEY",        "meta-llama/llama-4-scout-17b-16e-instruct")
    add("Cerebras",    "https://api.cerebras.ai/v1/chat/completions",                       "CEREBRAS_API_KEY",    "llama3.3-70b")
    add("SambaNova",   "https://api.sambanova.ai/v1/chat/completions",                      "SAMBANOVA_API_KEY",   "DeepSeek-V3.1")
    add("Together",    "https://api.together.xyz/v1/chat/completions",                      "TOGETHER_API_KEY",    "meta-llama/Llama-3.3-70B-Instruct-Turbo")
    add("Fireworks",   "https://api.fireworks.ai/inference/v1/chat/completions",            "FIREWORKS_API_KEY",   "accounts/fireworks/models/llama-v3p3-70b-instruct")
    add("Deepinfra",   "https://api.deepinfra.com/v1/openai/chat/completions",              "DEEPINFRA_API_KEY",   "meta-llama/Llama-3.3-70B-Instruct")
    add("NVIDIA",      "https://integrate.api.nvidia.com/v1/chat/completions",              "NVIDIA_API_KEY",      "meta/llama-3.3-70b-instruct")
    add("Mistral",     "https://api.mistral.ai/v1/chat/completions",                        "MISTRAL_API_KEY",     "mistral-small-latest")
    add("Novita",      "https://api.novita.ai/v3/openai/chat/completions",                  "NOVITA_API_KEY",      "meta-llama/llama-3.3-70b-instruct")
    add("Kluster",     "https://api.kluster.ai/v1/chat/completions",                        "KLUSTER_API_KEY",     "klusterai/Meta-Llama-3.3-70B-Instruct-Turbo")
    add("OpenRouter",  "https://openrouter.ai/api/v1/chat/completions",                     "OPENROUTER_API_KEY",  "meta-llama/llama-3.3-70b-instruct:free", _OR)
    add("Perplexity",  "https://api.perplexity.ai/chat/completions",                        "PERPLEXITY_API_KEY",  "llama-3.1-sonar-large-128k-online")
    add("XAI",         "https://api.x.ai/v1/chat/completions",                              "XAI_API_KEY",         "grok-3-mini-fast")
    add("HuggingFace", "https://api-inference.huggingface.co/v1/chat/completions",          "HUGGINGFACE_API_KEY", "Qwen/Qwen2.5-72B-Instruct")
    add("Cohere",      "https://api.cohere.com/compatibility/v1/chat/completions",          "COHERE_API_KEY",      "command-r-plus-08-2024")
    add("AI21",        "https://api.ai21.com/studio/v1/chat/completions",                   "AI21_API_KEY",        "jamba-1.5-mini")
    add("DeepSeek",    "https://api.deepseek.com/v1/chat/completions",                      "DEEPSEEK_API_KEY",    "deepseek-chat")
    add("ZAI",         f'{os.getenv("ZAI_BASE_URL","https://api.z.ai/api/paas/v4")}/chat/completions', "ZAI_API_KEY", os.getenv("ZAI_MODEL", "GLM-4.5"))
    return providers


async def _store_lesson(redis: aioredis.Redis, provider: str, symbol: str, pnl_pct: float, lesson: str):
    entry = {
        "ts":       time.time(),
        "symbol":   symbol,
        "provider": provider,
        "pnl_pct":  pnl_pct,
        "outcome":  "win" if pnl_pct > 0 else "loss",
        "category": "multi_llm_trade",
        "lesson":   lesson.strip(),
    }
    await redis.lpush("training:lessons", json.dumps(entry))
    await redis.ltrim("training:lessons", 0, 199)  # keep last 200 lessons
    log.debug(f"Multi-LLM [{provider}] ders kaydedildi: {symbol}")


async def analyze_trade_with_all_llms(redis: aioredis.Redis, trade: dict):
    """Called when a trade closes — ALL providers analyze it simultaneously."""
    symbol  = trade.get("symbol", "")
    pnl_pct = float(trade.get("pnl_pct", 0))

    # Load entry features (full feature dict, not ML vector)
    feat_raw = await redis.get(f"features:latest:{symbol}")
    features: dict | None = None
    if feat_raw:
        parsed = json.loads(feat_raw)
        features = parsed if isinstance(parsed, dict) else None

    prompt = _build_prompt(trade, features)
    providers = _get_providers()

    async with aiohttp.ClientSession() as session:
        tasks = []

        # Cloud providers
        for p in providers:
            tasks.append(_call_openai_compat(
                p["url"], p["key"], p["model"], prompt, p["extra"], session
            ))

        # Local Ollama always runs
        tasks.append(_call_ollama(prompt, session))
        provider_names = [p["name"] for p in providers] + ["Ollama"]

        results = await asyncio.gather(*tasks, return_exceptions=True)

    stored = 0
    for name, result in zip(provider_names, results):
        if isinstance(result, str) and result.strip():
            await _store_lesson(redis, name, symbol, pnl_pct, result)
            stored += 1

    log.info(f"Multi-LLM analiz: {symbol} pnl={pnl_pct:+.2f}% — {stored}/{len(provider_names)} provider ders yazdı")


async def multi_llm_trade_loop(redis_url: str):
    """Subscribe to ch:trade_closed and trigger multi-LLM analysis."""
    redis_sub  = await aioredis.from_url(redis_url, decode_responses=True)
    redis_data = await aioredis.from_url(redis_url, decode_responses=True)
    pubsub = redis_sub.pubsub()
    await pubsub.subscribe("ch:trade_closed")
    log.info("Multi-LLM: ch:trade_closed dinleniyor — her trade'de tüm LLM'ler analiz yapacak")
    try:
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            try:
                trade = json.loads(msg["data"])
                # Run analysis without blocking the listener
                asyncio.create_task(analyze_trade_with_all_llms(redis_data, trade))
            except Exception as e:
                log.warning(f"Multi-LLM mesaj işleme hatası: {e}")
    except Exception as e:
        log.error(f"Multi-LLM trade loop çöktü: {e}")
    finally:
        await redis_sub.aclose()
        await redis_data.aclose()
