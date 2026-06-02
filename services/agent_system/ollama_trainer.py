"""
Ollama model trainer — periodically builds a custom 'prometheus-trading' model
from accumulated trade knowledge (lessons, win rates, agent accuracy).

The model grows smarter over time. After years of trading it can work standalone.
Runs every 2 hours. Requires Ollama API at OLLAMA_URL.
"""
import asyncio
import json
import logging
import time
import os

import aiohttp
import redis.asyncio as aioredis

log = logging.getLogger(__name__)

OLLAMA_URL      = os.getenv("OLLAMA_URL", "http://ollama:11434")
BASE_MODEL      = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
TRAINED_MODEL   = "prometheus-trading"
TRAIN_INTERVAL  = 7200   # rebuild every 2 hours
MIN_KNOWLEDGE   = 200    # minimum chars before building


async def _collect_knowledge(redis: aioredis.Redis) -> str:
    """Gather all accumulated knowledge from Redis into a single knowledge base."""
    sections: list[str] = []

    # Trade lessons (all categories)
    lesson_keys = [
        ("training:lessons",          "KAPANAN TRADE DERSLERİ"),
        ("training:lessons:signals",  "SİNYAL KALIP DERSLERİ"),
        ("training:lessons:regime",   "REJİM DEĞİŞİM DERSLERİ"),
        ("training:lessons:blocked",  "BLOK DERSLERİ"),
    ]
    for key, title in lesson_keys:
        try:
            items = await redis.lrange(key, 0, 39)
            if items:
                lines = [f"\n### {title}"]
                for item in items:
                    try:
                        data = json.loads(item)
                        lesson = data.get("lesson") or data.get("text") or str(data)[:200]
                        lines.append(f"- {lesson}")
                    except Exception:
                        text = item.decode() if isinstance(item, bytes) else str(item)
                        lines.append(f"- {text[:200]}")
                sections.append("\n".join(lines))
        except Exception as e:
            log.debug(f"Knowledge collect [{key}]: {e}")

    # Win rates by regime + direction
    try:
        patterns_raw = await redis.get("agent:learned_patterns")
        if patterns_raw:
            patterns = json.loads(patterns_raw)
            lines = ["\n### REJİM × YÖN KAZANMA ORANLARI"]
            for k, v in patterns.items():
                if ":" in k and not k.endswith(":n"):
                    n = int(patterns.get(f"{k}:n", 0))
                    if n >= 3:
                        lines.append(f"- {k}: %{float(v)*100:.0f} kazanma ({n} trade)")
            if len(lines) > 1:
                sections.append("\n".join(lines))
    except Exception as e:
        log.debug(f"Knowledge collect [patterns]: {e}")

    # Agent accuracy
    try:
        summary_raw = await redis.get("agents:performance_summary")
        if summary_raw:
            perf = json.loads(summary_raw)
            lines = ["\n### AJAN DOĞRULUK İSTATİSTİKLERİ"]
            for agent, stats in perf.items():
                acc = float(stats.get("accuracy", 0))
                calls = int(stats.get("calls", 0))
                if calls > 0:
                    lines.append(f"- {agent}: %{acc*100:.0f} doğruluk ({calls} çağrı)")
            if len(lines) > 1:
                sections.append("\n".join(lines))
    except Exception as e:
        log.debug(f"Knowledge collect [agent_perf]: {e}")

    # Overall system stats
    try:
        stats_raw = await redis.get("signal_engine:stats")
        if stats_raw:
            stats = json.loads(stats_raw)
            total_trades = int(stats.get("total_trades", 0))
            win_rate = float(stats.get("overall_win_rate", 0))
            if total_trades > 0:
                sections.append(
                    f"\n### GENEL PERFORMANS\n"
                    f"- Toplam trade: {total_trades}\n"
                    f"- Genel kazanma oranı: %{win_rate*100:.1f}"
                )
    except Exception as e:
        log.debug(f"Knowledge collect [stats]: {e}")

    # Shadow system performance
    try:
        shadow_raw = await redis.get("shadow:stats")
        if shadow_raw:
            ss = json.loads(shadow_raw)
            lines = ["\n### SHADOW SİSTEM PERFORMANSI"]
            for k, v in ss.items():
                lines.append(f"- {k}: {v}")
            sections.append("\n".join(lines))
    except Exception as e:
        log.debug(f"Knowledge collect [shadow]: {e}")

    # Market depth / order book patterns learned from trades
    try:
        depth_lessons = await redis.lrange("training:lessons:depth", 0, 19)
        if depth_lessons:
            lines = ["\n### PİYASA DERİNLİK DERSLERİ (ORDER BOOK)"]
            for item in depth_lessons:
                try:
                    d = json.loads(item)
                    lesson = d.get("lesson") or d.get("text") or str(d)[:200]
                    lines.append(f"- {lesson}")
                except Exception:
                    lines.append(f"- {str(item)[:200]}")
            sections.append("\n".join(lines))
    except Exception as e:
        log.debug(f"Knowledge collect [depth]: {e}")

    # Funding rate behavior patterns
    try:
        funding_raw = await redis.get("market:funding_patterns")
        if funding_raw:
            fp = json.loads(funding_raw)
            lines = ["\n### FONLAMA ORANI KALIPLARI"]
            for pattern, stats in fp.items():
                lines.append(f"- {pattern}: {stats}")
            sections.append("\n".join(lines))
    except Exception as e:
        log.debug(f"Knowledge collect [funding]: {e}")

    # Training documents (titles + first 500 chars each)
    try:
        docs_raw = await redis.get("training:docs")
        if docs_raw:
            docs = json.loads(docs_raw)
            if docs:
                lines = ["\n### EĞİTİM DOKÜMANLARI ÖZETİ"]
                char_budget = 8000
                for doc in docs:
                    title = doc.get("title", "?")
                    content = doc.get("content", "")[:500]
                    entry = f"[{title}] {content}"
                    if char_budget <= 0:
                        break
                    lines.append(entry[:char_budget])
                    char_budget -= len(entry)
                sections.append("\n".join(lines))
    except Exception as e:
        log.debug(f"Knowledge collect [docs]: {e}")

    # Hardcoded market mechanics (always included)
    sections.append("""
### PİYASA MEKANİKLERİ (TEMEL BİLGİ)
- RSI > 70: Aşırı alım → SHORT olasılığı artar. RSI < 30: Aşırı satım → LONG olasılığı artar
- MACD hist pozitif → yukarı momentum. Negatif → aşağı momentum
- Funding rate > 0.03%: LONG'lar SHORT'lara ödeme yapar → aşırı LONG pozisyon tehlikeli
- Funding rate < -0.03%: SHORT'lar LONG'lara ödeme yapar → sıkışma riski
- OI (açık faiz) artarken fiyat düşüyor → SHORT baskısı güçlü
- OI artarken fiyat yükseliyor → LONG momentum güçlü
- OI düşüyor + fiyat düşüyor → LONG pozisyonları kapatılıyor (zayıf)
- Hacim oranı > 2x: Anormal hacim → trend değişimi veya kırılım sinyali
- ADX > 25: Güçlü trend. ADX < 20: Yatay piyasa (ranging)
- VIX > 40: Piyasa panik modunda → FLAT tercih et, leverage düşür
- BB (Bollinger) üst bant kırılımı → aşırı alım veya güçlü breakout
- Trending_down rejimde SHORT ağırlıklı işlem yap
- Volatile rejimde FLAT'te kal, risk düşür
- Ranging rejimde support-resistance al-sat stratejisi
- Zarar eden trade'den sonra aynı yönde trade açma — piyasa koşulları değişmemiş olabilir
- Kaldıraç: Maksimum 3x. Daha yüksek kaldıraç = daha yüksek tasfiye riski
- Pozisyon büyüklüğü: Portfolyonun maksimum %5'i tek trade'de""")

    return "\n".join(sections)


async def _create_model(knowledge: str) -> bool:
    """Create/update prometheus-trading Ollama model with embedded knowledge."""
    system_prompt = f"""Sen Prometheus Trading AI'sın — Binance USDM Futures için özelleşmiş kripto para alım-satım sistemi.

GÖREV: Piyasa koşullarını analiz edip LONG/SHORT/FLAT kararı ver.

ÇIKTI FORMATI (JSON — kesinlikle bu format):
{{"signal":"long|short|flat","confidence":0.0-1.0,"reasoning":"max 15 kelime"}}

TEMEL KURALLAR:
- Güven skoru > 0.65 olmadıkça FLAT kal
- Trending_down rejiminde SHORT'a yönel, LONG güvenini düşür
- Volatile rejimde FLAT tercih et
- Maksimum kaldıraç 3x, maksimum pozisyon portföyün %5'i
- Güçlü trend karşısında işlem açma
- Her trade'den ders çıkar, aynı hatayı tekrarlama

{knowledge}

Bu bilgileri her kararında uygula. Geçmiş hatalarından öğren, kazananı takip et."""

    modelfile = f'FROM {BASE_MODEL}\nSYSTEM """{system_prompt}"""'

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OLLAMA_URL}/api/create",
                json={"name": TRAINED_MODEL, "modelfile": modelfile},
                timeout=aiohttp.ClientTimeout(total=600),
            ) as resp:
                if resp.status == 200:
                    # Consume streamed response to completion
                    async for _ in resp.content:
                        pass
                    log.info(f"Ollama: '{TRAINED_MODEL}' modeli oluşturuldu/güncellendi "
                             f"({len(knowledge)} karakter bilgi)")
                    return True
                else:
                    body = await resp.text()
                    log.error(f"Ollama create hata: {resp.status} — {body[:200]}")
                    return False
    except Exception as e:
        log.error(f"Ollama trainer bağlantı hatası: {e}")
        return False


async def ollama_training_loop(redis: aioredis.Redis) -> None:
    """Main loop — rebuild prometheus-trading model every 2h with latest knowledge."""
    from llm_client import set_ollama_model

    # Check if already trained model exists on startup
    await asyncio.sleep(120)  # wait 2min for system to warm up

    while True:
        try:
            log.info("Ollama trainer: bilgi toplanıyor...")
            knowledge = await _collect_knowledge(redis)

            if len(knowledge) >= MIN_KNOWLEDGE:
                success = await _create_model(knowledge)
                if success:
                    set_ollama_model(TRAINED_MODEL)
                    await redis.set("ollama:trained_model",   TRAINED_MODEL,     ex=TRAIN_INTERVAL + 600)
                    await redis.set("ollama:last_train_ts",   str(time.time()),   ex=86400)
                    await redis.set("ollama:knowledge_chars", str(len(knowledge)), ex=86400)
                    log.info(f"Ollama eğitim tamamlandı — aktif model: {TRAINED_MODEL}")
            else:
                log.info(f"Ollama trainer: yeterli bilgi yok ({len(knowledge)} < {MIN_KNOWLEDGE}), atlanıyor")

        except Exception as e:
            log.error(f"Ollama training loop hatası: {e}")

        await asyncio.sleep(TRAIN_INTERVAL)
