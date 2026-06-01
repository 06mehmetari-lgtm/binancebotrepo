"""Gerçek zamanlı coin haber analizi — çoklu LLM sağlayıcı desteği.

CryptoPanic API'sinden haber başlıkları çeker, llm_client üzerinden
Groq → Cerebras → SambaNova → OpenRouter zinciriyle analiz eder.
Sonucu `news:groq:{SYMBOL}` Redis anahtarına yazar.
"""
import asyncio
import json
import logging
import os
import time

import aiohttp
import redis.asyncio as aioredis

log = logging.getLogger(__name__)

CRYPTOPANIC_KEY = os.getenv("CRYPTOPANIC_KEY", "")
NEWS_TTL        = 300   # 5 dk cache
SCAN_INTERVAL   = 120   # 2 dk'da bir tarama
MAX_SYMBOLS     = 30    # Tek turda max 30 sembol


async def _fetch_headlines(session: aiohttp.ClientSession, coin: str) -> list[str]:
    if not CRYPTOPANIC_KEY:
        return []
    url = (
        f"https://cryptopanic.com/api/v1/posts/"
        f"?auth_token={CRYPTOPANIC_KEY}&currencies={coin}"
        f"&public=true&filter=news&kind=news"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return [item["title"] for item in data.get("results", [])[:8] if item.get("title")]
    except Exception as e:
        log.debug(f"CryptoPanic {coin}: {e}")
        return []


async def _analyze_headlines(symbol: str, headlines: list[str]) -> dict:
    """Analyze headlines using multi-provider LLM client."""
    from llm_client import chat_completion
    coin = symbol.replace("USDT", "").replace("1000", "")
    lines = "\n".join(f"• {h}" for h in headlines[:6])
    prompt = (
        f"{coin} kripto para için son haberler:\n{lines}\n\n"
        f"Bu haberlerin kısa vadeli {coin}/USDT fiyatına etkisini değerlendir.\n"
        f"Yalnızca JSON döndür (başka metin ekleme):\n"
        f'{{"score":<-1.0 ile 1.0>,"signal":"<long/short/flat>",'
        f'"confidence":<0.0-1.0>,"summary":"<Türkçe 1 cümle özet>",'
        f'"key_factor":"<en kritik bilgi>"}}'
    )
    try:
        raw, _provider = await chat_completion(prompt, max_tokens=150)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        log.debug(f"Haber analiz hatası {symbol}: {e}")
    return {"score": 0.0, "signal": "flat", "confidence": 0.2, "summary": ""}


def _any_key_available() -> bool:
    for env in ("GROQ_API_KEY", "CEREBRAS_API_KEY", "SAMBANOVA_API_KEY", "OPENROUTER_API_KEY"):
        if os.getenv(env, ""):
            return True
    return False


class GroqNewsScanner:
    """Aktif sinyalli ve pozisyonlu coinler için gerçek zamanlı haber + AI analizi."""

    async def run(self, redis: aioredis.Redis):
        if not _any_key_available():
            log.warning("GroqNewsScanner: hiçbir LLM API key tanımlı değil — devre dışı")
            return
        if not CRYPTOPANIC_KEY:
            log.warning("GroqNewsScanner: CRYPTOPANIC_KEY eksik — devre dışı")
            return

        log.info("GroqNewsScanner başladı — çoklu LLM sağlayıcı desteği")

        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    await self._scan(session, redis)
                except Exception as e:
                    log.error(f"GroqNewsScanner döngü hatası: {e}")
                await asyncio.sleep(SCAN_INTERVAL)

    async def _scan(self, session: aiohttp.ClientSession, redis: aioredis.Redis):
        sig_keys = await redis.keys("signal:latest:*")
        pos_keys = await redis.keys("oms:position:*")

        syms: set[str] = set()
        for k in list(sig_keys)[:40] + list(pos_keys):
            s = (k.decode() if isinstance(k, bytes) else k).split(":")[-1].upper()
            syms.add(s)

        processed = 0
        for symbol in list(syms):
            if processed >= MAX_SYMBOLS:
                break
            coin = symbol.replace("USDT", "").replace("1000", "")
            if not (2 <= len(coin) <= 10 and coin.isalpha()):
                continue
            try:
                headlines = await _fetch_headlines(session, coin)
                if not headlines:
                    continue
                result = await _analyze_headlines(symbol, headlines)
                result["headlines"] = headlines[:5]
                result["timestamp"] = time.time()
                await redis.set(f"news:groq:{symbol}", json.dumps(result), ex=NEWS_TTL)
                processed += 1
                log.debug(
                    f"[Haber] {symbol}: {result.get('signal','?')} "
                    f"güven={result.get('confidence',0):.2f} — {result.get('summary','')[:60]}"
                )
            except Exception as e:
                log.debug(f"GroqNewsScanner skip {symbol}: {e}")
            await asyncio.sleep(0.4)
