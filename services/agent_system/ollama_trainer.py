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
TRAIN_INTERVAL  = 300    # rebuild every 5 minutes
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

    # Market consensus (anlık piyasa durumu)
    try:
        consensus_raw = await redis.get("market:consensus")
        if consensus_raw:
            c = json.loads(consensus_raw)
            bull   = c.get("market_bull_pct", 0) * 100
            bear   = c.get("market_bear_pct", 0) * 100
            score  = c.get("market_consensus", 0)
            btc    = c.get("btc_trend", 0)
            eth    = c.get("eth_trend", 0)
            active = c.get("market_active_count", 0)
            mood   = (
                "GÜÇLÜ BOĞA" if score >  0.5 else
                "BOĞA"       if score >  0.2 else
                "GÜÇLÜ AYI"  if score < -0.5 else
                "AYI"        if score < -0.2 else
                "NÖTR"
            )
            btc_txt = "yukarı" if btc > 0 else "aşağı" if btc < 0 else "nötr"
            eth_txt = "yukarı" if eth > 0 else "aşağı" if eth < 0 else "nötr"
            sections.append(
                f"\n### ANLK PİYASA CONSENSUS\n"
                f"- Piyasa durumu: {mood} (skor: {score:+.2f})\n"
                f"- Boğa sinyal: %{bull:.0f} | Ayı sinyal: %{bear:.0f}\n"
                f"- Aktif sinyal sayısı: {active}\n"
                f"- BTC trendi: {btc_txt} | ETH trendi: {eth_txt}\n"
                f"- Yorum: Piyasanın %{max(bull, bear):.0f}'i "
                f"{'LONG' if bull >= bear else 'SHORT'} — "
                f"bu yönde işlem {'güvenli' if max(bull, bear) > 60 else 'dikkatli'}"
            )
    except Exception as e:
        log.debug(f"Knowledge collect [consensus]: {e}")

    # Hardcoded market mechanics — all indicators (always included)
    sections.append("""
### PİYASA MEKANİKLERİ VE İNDİKATÖR KILAVUZU (TEMEL BİLGİ)

## TREND İNDİKATÖRLERİ
- EMA 20 > EMA 50 > EMA 200 = güçlü boğa trendi (Golden Cross). Tersi = ayı trendi (Death Cross)
- Fiyat EMA 200 üstünde → uzun vadeli boğa. Altında → uzun vadeli ayı
- HMA (Hull MA) = düşük gecikmeli trend yönü — ani dönüşleri erken yakalar
- Supertrend yönü = +1 (boğa, fiyat üstte) / -1 (ayı, fiyat altta). Yön değişimi = güçlü sinyal
- Supertrend mesafesi < 1 ATR: Stop seviyesi yakın, dikkatli ol
- Parabolic SAR boğa (psar_bull=1): fiyat SAR'ın üstünde → LONG eğilimi
- Parabolic SAR ayı (psar_bull=0): fiyat SAR'ın altında → SHORT eğilimi
- Donchian pozisyon > 0.8: fiyat 20 günlük zirveye yakın → potansiyel breakout veya aşırı alım
- Donchian pozisyon < 0.2: fiyat 20 günlük dibe yakın → potansiyel destek veya aşırı satım

## İCHİMOKU BULUTU
- ichi_price_vs_cloud = +1: fiyat bulutun üstünde → GÜÇLÜ BOĞA — bulut destek
- ichi_price_vs_cloud = -1: fiyat bulutun altında → GÜÇLÜ AYI — bulut direnç
- ichi_price_vs_cloud = 0: fiyat bulutun içinde → NÖTR, yön belirsiz
- ichi_cloud_thick yüksek: bulut kalın = kırılması zor destek/direnç
- ichi_tk_cross > 0: Tenkan > Kijun → kısa vadeli boğa momentum
- ichi_chikou_signal > 0: Chikou 26 bar öncesinin fiyatının üstünde → boğa teyidi

## MOMENTUM İNDİKATÖRLERİ
- RSI > 70: Aşırı alım → SHORT olasılığı artar, momentum tükenebilir
- RSI < 30: Aşırı satım → LONG olasılığı artar, dipten dönüş bekle
- RSI güçlü trende 14 gün 70 üstünde kalabilir — trendi görmezden gelme
- MACD hist pozitif ve artıyor → momentum hızlanıyor (LONG lehine)
- MACD hist negatif ve düşüyor → momentum hızlanıyor (SHORT lehine)
- MACD hist yönü fiyat yönüyle çelişiyorsa → UYUMSUZLUK (Divergence) = dönüş sinyali
- Stochastic K > 80: aşırı alım bölgesi. K < 20: aşırı satım bölgesi
- CCI > +100: güçlü yukarı hareket. CCI < -100: güçlü aşağı hareket
- Williams %R > -20: aşırı alım. < -80: aşırı satım

## TREND GÜCÜ / YÖN (ADX, AROON, VORTEX)
- ADX < 20: Yatay piyasa (ranging) → osilatörlere bak (RSI, Stochastic)
- ADX 20-40: Trend oluşuyor → trend takip stratejisi
- ADX > 40: Güçlü trend → trend karşıtı işlem açma!
- DI+ > DI- (di_cross > 0): alıcılar baskın → boğa trendi
- DI- > DI+ (di_cross < 0): satıcılar baskın → ayı trendi
- ADX divergence: fiyat yeni yüksek yaparken ADX düşüyorsa → trend zayıflıyor
- Aroon Up 100'e yakın + Aroon Down 0'a yakın: güçlü boğa trendi, tersine işlem yapma
- Aroon Up ve Down birbirini keserse → yeni trend başlıyor
- Aroon osc > 70: güçlü boğa. < -70: güçlü ayı. 0 civarı: ranging
- VI+ > VI- (vi_diff > 0): yukarı akış baskın → boğa. VI- > VI+: ayı
- VI+ ve VI- 1.20 üstüne çıkması → aşırı tek yönlü momentum

## HACİM ANALİZİ
- VWAP: Kurumsal ortalama maliyet fiyatı
  * Fiyat VWAP üstünde (price_above_vwap=1): kurumsal alımlar kazançta → LONG eğilimi
  * Fiyat VWAP altında: kurumsal alımlar zararda → satış baskısı olabilir
  * VWAP mesafesi > 3 ATR: fiyat VWAP'tan çok uzak → geri dönüş olası
- OBV değişimi pozitif: fiyat düşmeden hacim artıyor → birikim (accumulation) = LONG sinyali
- OBV değişimi negatif: fiyat yükselmeden hacim düşüyor → dağıtım (distribution) = SHORT sinyali
- CMF > 0.1: güçlü para girişi. CMF < -0.1: güçlü para çıkışı
- MFI > 80: aşırı alım (hacim destekli). MFI < 20: aşırı satım (hacim destekli)
- A/D Line artıyorken fiyat düşüyorsa → bullish divergence (dip yakın)
- Hacim oranı > 2x: anormal hacim → trend değişimi veya kırılım yakın
- Vol surge (vol_surge=1): patlama sinyali — yönü DI+ / DI- ile teyit et

## SMART MONEY CONCEPTS (SMC) — KURUMSAL PARA TAKİBİ
- struct_bullish = 1: HH + HL yapısı (Higher High + Higher Low) → boğa trendi onaylı
- struct_bearish = 1: LH + LL yapısı (Lower High + Lower Low) → ayı trendi onaylı
- bos_bullish = 1: Break of Structure yukarı → trend devam ediyor, LONG lehine
- bos_bearish = 1: Break of Structure aşağı → trend devam ediyor, SHORT lehine
- choch_bullish = 1: Change of Character — ayı trendi bitti, boğa başlıyor → LONG fırsatı
- choch_bearish = 1: Change of Character — boğa trendi bitti, ayı başlıyor → SHORT fırsatı
- price_in_bull_ob = 1: Fiyat boğa Order Block içinde → kurumsal alım bölgesi, LONG için ideal giriş
- price_in_bear_ob = 1: Fiyat ayı Order Block içinde → kurumsal satım bölgesi, SHORT için ideal giriş
- bull_fvg_dist küçük (< 1 ATR): Fiyat altındaki bir bullish FVG'ye yakın → destek gibi davranabilir
- bear_fvg_dist küçük (< 1 ATR): Fiyat üstündeki bir bearish FVG'ye yakın → direnç gibi davranabilir
- dist_to_resistance küçük (< 1 ATR): Güçlü direnç yakın → pozisyon büyüklüğünü küçült
- dist_to_support küçük (< 1 ATR): Güçlü destek yakın → LONG için güvenli alan
- CHoCH'u tespit edince aceleden işlem açma — gövde kapanışını (body close) bekle

## VOLATİLİTE
- ATR yüksek: büyük hareketler bekleniyor → stop mesafesini genişlet, pozisyonu küçült
- ATR düşük (piyasa sıkışık): Bollinger Squeeze oluşuyorsa büyük patlama yakın
- BB Squeeze (bb_squeeze düşük): bantlar daraldı → breakout gelecek, yönü DI+/DI- ile belirle
- Bollinger üst bandı kırılması: aşırı alım VEYA güçlü breakout (ADX ile teyit et)

## ÇOKLU ZAMAN DİLİMİ (MTF) CONFLUENCE
- trend_alignment_3tf > 0.5: 4 TF (1m/1h/4h/1d) boğa uyumu → yüksek kalite LONG sinyali
- trend_alignment_3tf < -0.5: 4 TF ayı uyumu → yüksek kalite SHORT sinyali
- major_bull_align = 2: 4H ve Daily aynı anda boğa → uzun vadeli trend güçlü
- major_bear_align = 2: 4H ve Daily aynı anda ayı → uzun vadeli trend aşağı
- 1m'de SHORT sinyali ama Daily trend yukarıysa → FLAT kal (trende karşı gitme)
- ichi_signal_4h = +1: 4H Ichimoku bulutunun üstünde → orta vadeli boğa teyidi
- adx_4h > 30 + trend_4h > 0: 4H'te güçlü boğa trendi → 1m long sinyallerini destekler

## KRİPTO ÖZGÜL VERİLER
- Funding rate > 0.03%: LONG'lar SHORT'lara ödeme yapar → aşırı LONG, sıkışma riski
- Funding rate < -0.03%: SHORT'lar LONG'lara ödeme yapar → aşırı SHORT, squeeze riski
- OI artarken fiyat yükseliyor → güçlü LONG momentum, trend sağlam
- OI artarken fiyat düşüyor → güçlü SHORT baskısı
- OI azalırken fiyat düşüyor → LONG'lar pozisyon kapatıyor (zayıf piyasa)
- OI azalırken fiyat yükseliyor → SHORT'lar kapatıyor (short squeeze)
- VIX > 40: panik modu → FLAT, leverage düşür
- Fear&Greed < 20: aşırı korku → dip yakın olabilir, LONG için izle
- Fear&Greed > 80: aşırı açgözlülük → zirve yakın olabilir, SHORT için izle

## REJİM STRATEJİLERİ
- trending_up rejimde: ADX > 25 olmadan LONG açma. EMA sıralanmış mı kontrol et
- trending_down rejimde: SHORT öncelikli. LONG sinyallerini %20 güven indirimi uygula
- ranging rejimde: Destek alıp dirence sat. RSI + Stochastic kullan, EMA'ları yoksay
- volatile rejimde: FLAT tercih et. Pozisyon açacaksan 0.5× normal büyüklükle aç

## RİSK YÖNETİMİ
- Maksimum kaldıraç: 3× — daha fazlası tasfiye (liquidation) riskini katlar
- Tek trade: maksimum portföyün %5'i
- Günlük zarar: %10'u geçerse FLAT — piyasayı anlayamıyorsun demektir
- Zarar eden trade'in hemen ardından aynı yönde işlem açma
- Order Block içine girmeden önce zaman dilimi uyumunu kontrol et
- FVG doldurulursa geçerliliğini yitirir — eski haritayı kullanma""")

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

    # Yeni Ollama API formatı (0.6+): from + system ayrı field
    # Eski format: modelfile string — her ikisini de dene
    async def _try_create(session: aiohttp.ClientSession, payload: dict) -> bool:
        async with session.post(
            f"{OLLAMA_URL}/api/create",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=600),
        ) as resp:
            if resp.status == 200:
                async for _ in resp.content:
                    pass
                return True
            body = await resp.text()
            log.debug(f"Ollama create deneme başarısız ({resp.status}): {body[:100]}")
            return False

    try:
        async with aiohttp.ClientSession() as session:
            # Önce yeni API formatını dene (Ollama 0.6+)
            success = await _try_create(session, {
                "model":  TRAINED_MODEL,
                "from":   BASE_MODEL,
                "system": system_prompt,
            })

            # Başarısız olursa eski Modelfile formatını dene
            if not success:
                modelfile = f'FROM {BASE_MODEL}\nSYSTEM """{system_prompt}"""'
                success = await _try_create(session, {
                    "name":      TRAINED_MODEL,
                    "modelfile": modelfile,
                })

            if success:
                log.info(f"Ollama: '{TRAINED_MODEL}' modeli oluşturuldu/güncellendi "
                         f"({len(knowledge)} karakter bilgi)")
                return True
            else:
                log.error("Ollama create hata: her iki format da başarısız")
                return False
    except Exception as e:
        log.error(f"Ollama trainer bağlantı hatası: {e}")
        return False


async def _check_ollama_alive() -> bool:
    """Return True if Ollama API responds to /api/tags."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{OLLAMA_URL}/api/tags",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
    except Exception as e:
        log.warning(f"Ollama bağlantı kontrolü başarısız: {e}")
        return False


async def ollama_training_loop(redis: aioredis.Redis) -> None:
    """Main loop — rebuild prometheus-trading model every 2h with latest knowledge."""
    from llm_client import set_ollama_model

    await asyncio.sleep(30)  # wait 30s for system to warm up

    while True:
        try:
            log.info("Ollama trainer: bilgi toplanıyor...")
            knowledge = await _collect_knowledge(redis)

            # Always write knowledge size so the dashboard can show it
            await redis.set("ollama:knowledge_chars", str(len(knowledge)), ex=86400)
            await redis.set("ollama:knowledge_preview", knowledge[:500], ex=86400)

            if len(knowledge) >= MIN_KNOWLEDGE:
                # Check connectivity before attempting the expensive model build
                if not await _check_ollama_alive():
                    log.warning("Ollama yanıt vermiyor — model oluşturma atlandı, sonraki döngüde tekrar denenecek")
                    await asyncio.sleep(TRAIN_INTERVAL)
                    continue

                success = await _create_model(knowledge)
                if success:
                    set_ollama_model(TRAINED_MODEL)
                    await redis.set("ollama:trained_model",   TRAINED_MODEL,      ex=TRAIN_INTERVAL + 600)
                    await redis.set("ollama:last_train_ts",   str(time.time()),    ex=86400)
                    await redis.set("ollama:knowledge_chars", str(len(knowledge)), ex=86400)
                    log.info(f"Ollama eğitim tamamlandı — aktif model: {TRAINED_MODEL}")
                else:
                    log.error("Ollama model oluşturma başarısız — bilgi boyutu Redis'e yazıldı ama model güncellenemedi")
            else:
                log.info(f"Ollama trainer: yeterli bilgi yok ({len(knowledge)} < {MIN_KNOWLEDGE}), atlanıyor")

        except Exception as e:
            log.error(f"Ollama training loop hatası: {e}")

        await asyncio.sleep(TRAIN_INTERVAL)
