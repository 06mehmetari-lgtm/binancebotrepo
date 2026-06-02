"""
Event Learner — Faz 2: Sistem geneli olay öğrenimi.

Her önemli sistem olayından AI dersi üretir ve training context'e enjekte eder.
Debate agent bu dersleri bir sonraki al/sat kararında kullanır.

Dinlenen kanallar:
  ch:trade_closed      → kazanç/kayıp dersi (lesson_writer ile birlikte çalışır)
  ch:immunity_blocked  → neden bloklandı, hangi kural devreye girdi
  ch:regime_changed    → piyasa rejimi değişti, ne yapmalı

Periyodik görevler:
  position_observer    → açık pozisyonlar %2+ hareket edince P&L dersi
  signal_tracker       → yüksek güvenli sinyallerin kalıp analizi

Redis yazılan listeler:
  training:lessons             → global, 100 max
  training:lessons:{SYMBOL}    → sembol bazlı, 20 max
  training:lessons:signals     → sinyal kalıpları, 50 max
  training:lessons:regime      → rejim dersleri, 30 max
  training:lessons:blocked     → blok dersleri, 30 max
  training:lessons:positions   → pozisyon evrimi, 50 max
"""

import asyncio
import json
import logging
import time

import redis.asyncio as aioredis

from llm_client import chat_completion

log = logging.getLogger(__name__)

# ── Limitler ─────────────────────────────────────────────────────────────────
MAX_GLOBAL      = 100
MAX_SYMBOL      = 20
MAX_SIGNALS     = 50
MAX_REGIME      = 30
MAX_BLOCKED     = 30
MAX_POSITIONS   = 50

# Pozisyon gözlemcisi: kaç % hareket edince ders üretilsin
POSITION_LESSON_THRESHOLD_PCT = 2.0


# ── Yardımcı: LLM ders üretici ───────────────────────────────────────────────

async def _llm_lesson(prompt: str, fallback: str) -> str:
    """LLM ile ders üret. Tüm providerlar başarısız olursa fallback döner."""
    try:
        content, provider = await chat_completion(prompt, temperature=0.2, max_tokens=250)
        lesson = content.strip()
        log.debug(f"EventLearner: ders üretildi [{provider}]")
        return lesson
    except Exception as e:
        log.warning(f"EventLearner: LLM başarısız, fallback kullanılıyor — {e}")
        return fallback


# ── Yardımcı: Redis'e kayıt ──────────────────────────────────────────────────

async def _store(redis: aioredis.Redis, data: dict, category: str = ""):
    """Dersi global + sembol + kategori listelerine yaz."""
    raw = json.dumps(data, ensure_ascii=False)

    await redis.lpush("training:lessons", raw)
    await redis.ltrim("training:lessons", 0, MAX_GLOBAL - 1)

    symbol = data.get("symbol", "")
    if symbol and symbol != "MARKET":
        await redis.lpush(f"training:lessons:{symbol}", raw)
        await redis.ltrim(f"training:lessons:{symbol}", 0, MAX_SYMBOL - 1)

    if category:
        limit_map = {
            "signals":   MAX_SIGNALS,
            "regime":    MAX_REGIME,
            "blocked":   MAX_BLOCKED,
            "positions": MAX_POSITIONS,
        }
        limit = limit_map.get(category, MAX_GLOBAL)
        await redis.lpush(f"training:lessons:{category}", raw)
        await redis.ltrim(f"training:lessons:{category}", 0, limit - 1)


# ── Olay işleyiciler ─────────────────────────────────────────────────────────

async def learn_from_debate(redis: aioredis.Redis, symbol: str, verdict: dict, features: dict | None):
    """
    Yüksek güvenli (≥0.65) debate sonuçlarından sinyal kalıp dersi üret.
    Hangi göstergeler bu sinyali tetikledi? Bu rejimde güvenilir mi?
    """
    direction   = verdict.get("direction", "flat")
    confidence  = float(verdict.get("confidence", 0))

    if direction == "flat" or confidence < 0.65:
        return

    regime   = verdict.get("regime", "unknown")
    rsi      = round(float(features["rsi_14"]), 1)    if features and features.get("rsi_14")      else "N/A"
    macd     = round(float(features["macd_hist"]), 4)  if features and features.get("macd_hist")   else "N/A"
    bb_pct   = f'{round(float(features["bb_pct"])*100)}%' if features and features.get("bb_pct") else "N/A"
    funding  = f'{round(float(features["funding_rate"])*100, 4)}%' if features and features.get("funding_rate") else "N/A"
    vol_r    = round(float(features["volume_ratio"]), 2) if features and features.get("volume_ratio") else "N/A"
    ls_ratio = round(float(features["long_short_ratio"]), 2) if features and features.get("long_short_ratio") else "N/A"
    reasoning = str(verdict.get("reasoning", ""))[:400]

    prompt = f"""9 ajanlı AI tartışması güçlü bir sinyal üretti. Bu kalıptan kısa bir ders çıkar.

Sembol: {symbol}
Sinyal: {direction.upper()} | Güven: {confidence:.0%} | Rejim: {regime}
RSI: {rsi} | MACD Hist: {macd} | BB%B: {bb_pct} | Hacim Oranı: {vol_r}x
Fonlama: {funding} | L/S Oranı: {ls_ratio}
Ajan Görüşü: {reasoning}

2 cümle yaz (Türkçe):
1. Bu sinyali hangi gösterge kombinasyonu tetikledi?
2. Bu rejimde bu sinyal ne kadar güvenilir ve ne zaman riskli olur?"""

    fallback = (
        f"{symbol}: {direction.upper()} sinyali — güven {confidence:.0%}, "
        f"rejim {regime}, RSI {rsi}, MACD {macd}."
    )
    lesson = await _llm_lesson(prompt, fallback)

    await _store(redis, {
        "ts":         time.time(),
        "symbol":     symbol,
        "category":   "signal",
        "direction":  direction,
        "confidence": confidence,
        "regime":     regime,
        "rsi":        rsi,
        "macd":       macd,
        "lesson":     lesson,
        "outcome":    "pending",
    }, category="signals")

    log.debug(f"EventLearner [sinyal]: {symbol} {direction.upper()} {confidence:.0%}")


async def learn_from_regime_change(
    redis: aioredis.Redis,
    old_regime: str,
    new_regime: str,
    features: dict | None,
):
    """
    Piyasa rejimi değiştiğinde ne yapmalı, ne yapmamalı?
    Hangi stratejiler yeni rejimde işe yarar?
    """
    vix      = features.get("vix_level",       "N/A") if features else "N/A"
    fg       = features.get("fear_greed",       "N/A") if features else "N/A"
    funding  = features.get("funding_rate",     "N/A") if features else "N/A"
    btc_chg  = features.get("price_change_1h",  "N/A") if features else "N/A"

    prompt = f"""Kripto vadeli işlem piyasasında rejim değişikliği oldu. Pratik bir strateji dersi üret.

Eski Rejim: {old_regime}  →  Yeni Rejim: {new_regime}
VIX: {vix} | Fear&Greed: {fg}/100 | Fonlama: {funding} | BTC 1s Değişim: {btc_chg}

3 cümle yaz (Türkçe):
1. Bu rejim değişikliği piyasa için ne anlama geliyor?
2. Yeni rejimde hangi strateji ve göstergeler öne çıkmalı?
3. Hangi işlemlerden kaçınılmalı veya hangi limitler daraltılmalı?"""

    fallback = (
        f"Piyasa rejimi {old_regime} → {new_regime} değişti. "
        f"VIX: {vix}, Fear&Greed: {fg}. Strateji buna göre ayarlanmalı."
    )
    lesson = await _llm_lesson(prompt, fallback)

    await _store(redis, {
        "ts":         time.time(),
        "symbol":     "MARKET",
        "category":   "regime",
        "old_regime": old_regime,
        "new_regime": new_regime,
        "vix":        vix,
        "fear_greed": fg,
        "lesson":     lesson,
    }, category="regime")

    log.info(f"EventLearner [rejim]: {old_regime} → {new_regime} — ders kaydedildi")


async def learn_from_immunity_block(redis: aioredis.Redis, event: dict):
    """
    Immunity sistemi bir işlemi bloklandığında ne öğrenilmeli?
    Hangi kural devreye girdi, gelecekte bu durumdan nasıl avantaj sağlanır?
    """
    symbol     = event.get("symbol",     "")
    side       = event.get("side",       "")
    reason     = event.get("reason",     "")
    confidence = float(event.get("confidence", 0))
    size_usd   = event.get("size_usd",   "N/A")
    regime     = event.get("regime",     "unknown")

    prompt = f"""Risk yönetimi sistemi bir işlemi engelledi. Bu bloktan bir ders çıkar.

Sembol: {symbol} | Yön: {side.upper()} | Güven: {confidence:.0%}
Blok Sebebi: {reason}
İşlem Büyüklüğü: ${size_usd} | Rejim: {regime}

2 cümle yaz (Türkçe):
1. Bu blok doğru muydu, neden bu kural devreye girdi?
2. Bu durumda ne yapılmalıydı veya bir dahaki seferde nasıl işlem açılabilir?"""

    fallback = f"{symbol} {side.upper()} işlemi bloklandı: {reason}. Güven: {confidence:.0%}."
    lesson = await _llm_lesson(prompt, fallback)

    await _store(redis, {
        "ts":         time.time(),
        "symbol":     symbol,
        "category":   "blocked",
        "side":       side,
        "reason":     reason,
        "confidence": confidence,
        "regime":     regime,
        "lesson":     lesson,
    }, category="blocked")

    log.info(f"EventLearner [blok]: {symbol} {side} — {reason}")


async def learn_from_position_pnl(
    redis: aioredis.Redis,
    symbol: str,
    position: dict,
    pnl_pct: float,
    current_price: float,
):
    """
    Açık pozisyon %2+ hareket ettiğinde momentum ve çıkış kararı için ders üret.
    Ters mühendislik: bu hareketten nasıl daha fazla kazanılır veya zarar kısaltılır?
    """
    side         = position.get("side", "BUY")
    entry        = float(position.get("entry_price", 0))
    regime       = position.get("entry_regime",  "unknown")
    tp_pct       = position.get("tp_pct",  None)
    sl_pct       = position.get("stop_pct", None)
    hold_min     = (time.time() - float(position.get("open_time", time.time()))) / 60
    agent_dir    = position.get("agent_direction", side.lower())
    momentum     = "güçleniyor" if (pnl_pct > 0 and side == "BUY") or (pnl_pct < 0 and side == "SELL") else "zayıflıyor"

    tp_info  = f"TP: +{tp_pct}%"  if tp_pct  else "TP: tanımsız"
    sl_info  = f"SL: {sl_pct}%"   if sl_pct  else "SL: tanımsız"

    prompt = f"""Açık bir kripto vadeli işlem pozisyonu önemli ölçüde hareket etti. Anlık bir gözlem dersi üret.

Sembol: {symbol} | Yön: {side.upper()} | Giriş: ${entry:.4f} | Anlık: ${current_price:.4f}
P&L: {pnl_pct:+.2f}% | Tutma Süresi: {hold_min:.0f} dk | Rejim: {regime}
{tp_info} | {sl_info} | Momentum: {momentum}
Ajan Yönü: {agent_dir}

2 cümle yaz (Türkçe):
1. Bu fiyat hareketi pozisyon için ne anlama geliyor, momentum sürüyor mu?
2. Şu anda en iyi strateji tutmak mı, çıkmak mı, yoksa TP/SL ayarlamak mı?"""

    yön = "kâr" if pnl_pct > 0 else "zarar"
    fallback = (
        f"{symbol} {side.upper()} pozisyon {pnl_pct:+.2f}% {yön}da, "
        f"{hold_min:.0f} dakika tutuldu. Momentum: {momentum}."
    )
    lesson = await _llm_lesson(prompt, fallback)

    await _store(redis, {
        "ts":          time.time(),
        "symbol":      symbol,
        "category":    "position_pnl",
        "side":        side,
        "pnl_pct":     round(pnl_pct, 2),
        "hold_min":    round(hold_min, 1),
        "price":       current_price,
        "regime":      regime,
        "momentum":    momentum,
        "lesson":      lesson,
    }, category="positions")

    log.info(f"EventLearner [pozisyon]: {symbol} {side} {pnl_pct:+.2f}% — ders kaydedildi")


# ── Periyodik görevler ────────────────────────────────────────────────────────

async def position_observer_loop(redis: aioredis.Redis):
    """
    Her 60 saniyede açık pozisyonları izle.
    %2+ hareket edince P&L dersi üret.
    """
    # symbol → son ders üretildiğindeki pnl_pct
    last_lesson_pnl: dict[str, float] = {}

    while True:
        try:
            keys = await redis.keys("positions:open:*")
            active_symbols: set[str] = set()

            for key in keys:
                try:
                    raw = await redis.get(key)
                    if not raw:
                        continue
                    pos    = json.loads(raw)
                    symbol = pos.get("symbol", "")
                    entry  = float(pos.get("entry_price", 0))
                    side   = pos.get("side", "BUY")
                    if not entry or not symbol:
                        continue

                    active_symbols.add(symbol)

                    # Fiyat al: ticker → features fallback
                    price = 0.0
                    ticker_raw = await redis.get(f"binance:ticker:{symbol.lower()}")
                    if ticker_raw:
                        td  = json.loads(ticker_raw)
                        d   = td.get("data", td)
                        bid = float(d.get("b", d.get("bid", 0)) or 0)
                        ask = float(d.get("a", d.get("ask", bid)) or bid)
                        price = (bid + ask) / 2 if bid and ask else bid or ask
                    if not price:
                        feat_raw = await redis.get(f"features:latest:{symbol}")
                        if feat_raw:
                            price = float(json.loads(feat_raw).get("close", 0) or 0)
                    if not price:
                        continue

                    pnl_pct = (
                        (price - entry) / entry * 100 if side == "BUY"
                        else (entry - price) / entry * 100
                    )

                    last = last_lesson_pnl.get(symbol, pnl_pct)
                    if abs(pnl_pct - last) >= POSITION_LESSON_THRESHOLD_PCT:
                        await learn_from_position_pnl(redis, symbol, pos, pnl_pct, price)
                        last_lesson_pnl[symbol] = pnl_pct

                except Exception as e:
                    log.debug(f"EventLearner pozisyon gözlem hatası {key}: {e}")

            # Kapanmış pozisyonları izleyiciden temizle
            last_lesson_pnl = {s: p for s, p in last_lesson_pnl.items() if s in active_symbols}

        except Exception as e:
            log.warning(f"EventLearner position_observer_loop hatası: {e}")

        await asyncio.sleep(60)


async def immunity_block_listener(redis_url: str):
    """
    ch:immunity_blocked kanalını dinle.
    OMS bir işlemi bloklandığında buraya yayın yapar.
    """
    redis_sub  = aioredis.from_url(redis_url, decode_responses=True)
    redis_data = aioredis.from_url(redis_url, decode_responses=True)
    try:
        pubsub = redis_sub.pubsub()
        await pubsub.subscribe("ch:immunity_blocked")
        log.info("EventLearner: ch:immunity_blocked dinleniyor")
        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            try:
                event = json.loads(msg["data"])
                await learn_from_immunity_block(redis_data, event)
            except Exception as e:
                log.warning(f"EventLearner immunity block işleme hatası: {e}")
    except Exception as e:
        log.error(f"EventLearner immunity_block_listener çöktü: {e}")
    finally:
        await redis_sub.aclose()
        await redis_data.aclose()


async def regime_change_listener(redis_url: str):
    """
    ch:regime_changed kanalını dinle.
    agent_system veya context_engine rejim değişince buraya yayın yapar.
    """
    redis_sub  = aioredis.from_url(redis_url, decode_responses=True)
    redis_data = aioredis.from_url(redis_url, decode_responses=True)
    try:
        pubsub = redis_sub.pubsub()
        await pubsub.subscribe("ch:regime_changed")
        log.info("EventLearner: ch:regime_changed dinleniyor")
        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            try:
                event = json.loads(msg["data"])
                old_r = event.get("old_regime", "unknown")
                new_r = event.get("new_regime", "unknown")

                # BTC features'ı ek bağlam için oku
                feat_raw = await redis_data.get("features:latest:BTCUSDT")
                features = json.loads(feat_raw) if feat_raw else None

                await learn_from_regime_change(redis_data, old_r, new_r, features)
            except Exception as e:
                log.warning(f"EventLearner regime change işleme hatası: {e}")
    except Exception as e:
        log.error(f"EventLearner regime_change_listener çöktü: {e}")
    finally:
        await redis_sub.aclose()
        await redis_data.aclose()


# ── Ana giriş noktası ─────────────────────────────────────────────────────────

async def event_learner_loop(redis: aioredis.Redis, redis_url: str):
    """Tüm olay öğrenimi döngülerini başlat."""
    log.info(
        "EventLearner başlatılıyor — "
        "sinyal kalıpları | rejim değişimleri | bloklar | pozisyon evrimi"
    )
    await asyncio.gather(
        position_observer_loop(redis),
        immunity_block_listener(redis_url),
        regime_change_listener(redis_url),
    )
