"""
System Observer — Faz 5: Tüm sistem olaylarını izle ve dashboard feed'ine yaz.

Dinlenen kanallar:
  ch:trade_closed      → kapanan trade olayı
  ch:immunity_blocked  → bloklanmış işlem
  ch:regime_changed    → piyasa rejimi değişimi

Periyodik görevler (30s):
  - Yeni açılan pozisyonları tespit et
  - Güçlü debate sinyallerini yakala
  - PDF öğrenme ilerlemesini izle
  - Strateji belgesi güncellemelerini yakala

Yazılan Redis key:
  observer:events  →  rolling 500 olay (JSON list)
"""

import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

log = logging.getLogger(__name__)

MAX_EVENTS = 500
POLL_INTERVAL = 30  # saniye


def _event(
    etype: str,
    level: str,
    title: str,
    detail: str = "",
    symbol: str = "",
    pnl_pct: float | None = None,
    icon: str = "●",
) -> dict:
    return {
        "ts":      time.time(),
        "type":    etype,
        "level":   level,
        "title":   title,
        "detail":  detail,
        "symbol":  symbol,
        "pnl_pct": pnl_pct,
        "icon":    icon,
    }


async def _push(redis: aioredis.Redis, ev: dict):
    raw = json.dumps(ev, ensure_ascii=False)
    await redis.lpush("observer:events", raw)
    await redis.ltrim("observer:events", 0, MAX_EVENTS - 1)


# ── Pub/Sub dinleyicileri ─────────────────────────────────────────────────────

async def _trade_close_listener(redis_url: str, write_redis: aioredis.Redis):
    r = aioredis.from_url(redis_url, decode_responses=True)
    try:
        ps = r.pubsub()
        await ps.subscribe("ch:trade_closed")
        async for msg in ps.listen():
            if msg["type"] != "message":
                continue
            try:
                trade = json.loads(msg["data"])
                symbol    = trade.get("symbol", "?")
                direction = str(trade.get("direction", trade.get("side", "?"))).upper()
                pnl       = float(trade.get("pnl_pct", 0))
                reason    = trade.get("close_reason", "unknown")
                conf      = float(trade.get("confidence", 0))
                regime    = trade.get("regime", trade.get("entry_regime", "?"))
                hold_s    = int(trade.get("hold_seconds", 0))
                hold_str  = (f"{hold_s//3600}sa {(hold_s%3600)//60}dk"
                             if hold_s >= 3600 else f"{hold_s//60}dk")

                is_win    = pnl > 0
                level     = "success" if is_win else "error"
                icon      = "▲" if is_win else "▼"
                pnl_str   = f"{pnl*100:+.2f}%"

                await _push(write_redis, _event(
                    etype   = "TRADE_CLOSE",
                    level   = level,
                    icon    = icon,
                    symbol  = symbol,
                    title   = f"{symbol} {direction} kapandı — {pnl_str}",
                    detail  = (f"Sebep: {reason} | Süre: {hold_str} | "
                               f"Güven: {conf:.0%} | Rejim: {regime}"),
                    pnl_pct = round(pnl, 4),
                ))
            except Exception as e:
                log.debug(f"Observer trade_close hata: {e}")
    finally:
        await r.aclose()


async def _immunity_listener(redis_url: str, write_redis: aioredis.Redis):
    r = aioredis.from_url(redis_url, decode_responses=True)
    try:
        ps = r.pubsub()
        await ps.subscribe("ch:immunity_blocked")
        async for msg in ps.listen():
            if msg["type"] != "message":
                continue
            try:
                ev   = json.loads(msg["data"])
                sym  = ev.get("symbol", "?")
                side = str(ev.get("side", "?")).upper()
                reason = ev.get("reason", "bilinmiyor")
                conf   = float(ev.get("confidence", 0))
                size   = ev.get("size_usd", 0)

                await _push(write_redis, _event(
                    etype  = "BLOCK",
                    level  = "warning",
                    icon   = "🛡",
                    symbol = sym,
                    title  = f"{sym} {side} engellendi",
                    detail = (f"Sebep: {reason} | Güven: {conf:.0%} | "
                              f"Boyut: ${size:.0f}"),
                ))
            except Exception as e:
                log.debug(f"Observer immunity_block hata: {e}")
    finally:
        await r.aclose()


async def _regime_listener(redis_url: str, write_redis: aioredis.Redis):
    r = aioredis.from_url(redis_url, decode_responses=True)
    try:
        ps = r.pubsub()
        await ps.subscribe("ch:regime_changed")
        async for msg in ps.listen():
            if msg["type"] != "message":
                continue
            try:
                ev  = json.loads(msg["data"])
                old = ev.get("old_regime", "?")
                new = ev.get("new_regime",  "?")

                icons = {
                    "trending_up":   "📈",
                    "trending_down": "📉",
                    "ranging":       "↔",
                    "volatile":      "⚡",
                }
                icon = icons.get(new, "🔄")

                await _push(write_redis, _event(
                    etype  = "REGIME",
                    level  = "info",
                    icon   = icon,
                    symbol = "MARKET",
                    title  = f"Piyasa rejimi değişti: {old} → {new}",
                    detail = f"Strateji ve pozisyon limitleri buna göre güncellendi",
                ))
            except Exception as e:
                log.debug(f"Observer regime_change hata: {e}")
    finally:
        await r.aclose()


# ── Periyodik gözlem ─────────────────────────────────────────────────────────

async def _poll_loop(redis: aioredis.Redis):
    """
    Her 30 saniyede bir sistemi tara:
    - Yeni açılan pozisyonları tespit et
    - Yeni debate sinyallerini yakala
    - PDF öğrenme ilerlemesini izle
    - Strateji belgesi güncellemesini yakala
    """
    known_positions:   set[str] = set()
    known_signal_ts:   dict[str, float] = {}
    known_doc_count:   int = 0
    known_strat_ts:    float = 0.0

    await asyncio.sleep(10)   # başlangıç gecikmesi

    while True:
        try:
            # ── Açık pozisyonlar ──────────────────────────────────────────────
            pos_keys = await redis.keys("positions:open:*")
            current_positions: set[str] = set()

            for pk in pos_keys:
                try:
                    raw = await redis.get(pk)
                    if not raw:
                        continue
                    pos    = json.loads(raw)
                    symbol = pos.get("symbol", "")
                    side   = str(pos.get("direction",
                               pos.get("side", "?"))).upper()
                    if not symbol:
                        continue

                    key = f"{symbol}:{side}"
                    current_positions.add(key)

                    if key not in known_positions:
                        entry  = float(pos.get("entry_price", 0))
                        size   = float(pos.get("size_usd", 0))
                        conf   = float(pos.get("confidence", 0))
                        regime = pos.get("entry_regime", "?")
                        await _push(redis, _event(
                            etype  = "TRADE_OPEN",
                            level  = "info",
                            icon   = "🟢",
                            symbol = symbol,
                            title  = f"{symbol} {side} pozisyon açıldı",
                            detail = (f"Giriş: ${entry:.4f} | Boyut: ${size:.0f} | "
                                      f"Güven: {conf:.0%} | Rejim: {regime}"),
                        ))
                except Exception:
                    pass

            known_positions = current_positions

            # ── Güçlü debate sinyalleri ───────────────────────────────────────
            # Tüm verdict key'leri tara — son 30s içinde yenilenmiş olanlar
            verdict_keys = await redis.keys("agents:verdict:*")
            for vk in verdict_keys[:30]:   # çok fazla symbol varsa ilk 30
                try:
                    raw = await redis.get(vk)
                    if not raw:
                        continue
                    v    = json.loads(raw)
                    ts   = float(v.get("timestamp", 0))
                    sym  = v.get("symbol", "")
                    dir_ = v.get("direction", "flat")
                    conf = float(v.get("confidence", 0))

                    if dir_ == "flat" or conf < 0.72:
                        continue
                    if known_signal_ts.get(sym, 0) >= ts:
                        continue

                    known_signal_ts[sym] = ts
                    consensus = float(v.get("consensus", 0))

                    await _push(redis, _event(
                        etype  = "SIGNAL",
                        level  = "info",
                        icon   = "📊",
                        symbol = sym,
                        title  = f"{sym} güçlü sinyal: {dir_.upper()}",
                        detail = (f"Güven: {conf:.0%} | Konsensüs: {consensus:.0%} | "
                                  f"Kaynak: 9-ajan tartışması"),
                    ))
                except Exception:
                    pass

            # ── PDF öğrenme ilerlemesi ────────────────────────────────────────
            docs_raw = await redis.get("training:docs")
            if docs_raw:
                docs = json.loads(docs_raw)
                doc_count = sum(1 for d in docs if d.get("source") == "pdf")

                if doc_count > known_doc_count:
                    new_count = doc_count - known_doc_count
                    known_doc_count = doc_count
                    await _push(redis, _event(
                        etype  = "PDF",
                        level  = "success",
                        icon   = "📚",
                        symbol = "SYSTEM",
                        title  = f"{new_count} yeni PDF öğrenildi",
                        detail = (f"Toplam {doc_count} PDF aktif — "
                                  f"al/sat kararları güncellendi"),
                    ))

                # Strateji belgesi güncellemesi
                for doc in docs:
                    if doc.get("source") == "ai_generated":
                        doc_ts = float(doc.get("created_at", 0))
                        if doc_ts > known_strat_ts:
                            known_strat_ts = doc_ts
                            tc = int(doc.get("trade_count", 0))
                            await _push(redis, _event(
                                etype  = "STRATEGY",
                                level  = "success",
                                icon   = "🧠",
                                symbol = "SYSTEM",
                                title  = "AI strateji belgesi güncellendi",
                                detail = (f"{tc} trade analiz edildi — "
                                          f"yeni kurallar aktif"),
                            ))
                        break

            # ── Kuyruk durumu ────────────────────────────────────────────────
            queue_len = await redis.llen("training:queue")
            if queue_len > 0:
                await redis.set("observer:queue_len", str(queue_len))

        except Exception as e:
            log.warning(f"Observer poll_loop hata: {e}")

        await asyncio.sleep(POLL_INTERVAL)


# ── Ana giriş noktası ─────────────────────────────────────────────────────────

async def system_observer_loop(redis: aioredis.Redis, redis_url: str):
    """Tüm gözlem döngülerini başlat."""
    log.info("SystemObserver başlatılıyor — sistem geneli olay akışı aktif")

    # Başlangıç olayı
    await _push(redis, _event(
        etype  = "SYSTEM",
        level  = "info",
        icon   = "🚀",
        symbol = "SYSTEM",
        title  = "Prometheus Trading Sistemi başlatıldı",
        detail = "9 ajan tartışma, RAG belleği, strateji üretici aktif",
    ))

    await asyncio.gather(
        _trade_close_listener(redis_url, redis),
        _immunity_listener(redis_url, redis),
        _regime_listener(redis_url, redis),
        _poll_loop(redis),
    )
