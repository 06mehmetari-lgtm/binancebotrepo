"""
Strategy Extractor — Faz 4: Otomatik strateji belgesi üretimi.

Her saatte bir son 200 trade dersini analiz eder:
  - Rejime göre kazanma oranı
  - Yöne (LONG/SHORT) göre performans
  - Rejim × Yön kombinasyonlarının başarı oranı
  - Kapanış sebebi analizi
  - Güven aralığı × kazanma oranı korelasyonu
  - En iyi / en kötü semboller

Sonuçları LLM'e gönderir → somut alım satım kuralları belgesi üretir.
Bu belge training:docs'a eklenir → bir sonraki debate'ten itibaren aktif.
"""

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone

import redis.asyncio as aioredis

from llm_client import chat_completion

log = logging.getLogger(__name__)

STRATEGY_INTERVAL_S    = int(os.getenv("STRATEGY_INTERVAL_S", str(60 * 60)))  # 1 saat
MIN_TRADES_FOR_EXTRACT = int(os.getenv("STRATEGY_MIN_TRADES",  "10"))           # en az 10 trade
MAX_LESSONS_TO_READ    = 200
STRATEGY_DOC_PREFIX    = "AI Öğrenilmiş Strateji"


# ── İstatistik hesaplama ──────────────────────────────────────────────────────

def _bucket_confidence(conf: float) -> str:
    if conf < 0.55: return "0.45-0.55"
    if conf < 0.65: return "0.55-0.65"
    if conf < 0.75: return "0.65-0.75"
    return "0.75+"


def _bucket_hold(hold_s: int) -> str:
    m = hold_s / 60
    if m < 15:  return "<15dk"
    if m < 60:  return "15-60dk"
    if m < 240: return "1-4sa"
    return ">4sa"


def _compute_stats(lessons: list[dict]) -> dict:
    """
    Trade dersleri listesinden istatistik sözlüğü hesapla.
    Sadece gerçek trade'leri (WIN/LOSS) işle.
    """
    trades = [
        l for l in lessons
        if l.get("outcome") in ("WIN", "LOSS") and l.get("pnl_pct") is not None
    ]

    if not trades:
        return {}

    total  = len(trades)
    wins   = sum(1 for t in trades if t["outcome"] == "WIN")
    pnls   = [float(t["pnl_pct"]) for t in trades]
    avg_pnl = sum(pnls) / len(pnls)

    # ── Rejim analizi ─────────────────────────────────────────────────────
    by_regime: dict[str, list] = defaultdict(list)
    for t in trades:
        by_regime[t.get("regime", "unknown")].append(t)

    regime_stats = {}
    for reg, items in by_regime.items():
        w = sum(1 for i in items if i["outcome"] == "WIN")
        regime_stats[reg] = {
            "count":    len(items),
            "win_rate": w / len(items),
            "avg_pnl":  sum(float(i["pnl_pct"]) for i in items) / len(items),
        }

    # ── Yön analizi ───────────────────────────────────────────────────────
    by_side: dict[str, list] = defaultdict(list)
    for t in trades:
        by_side[t.get("side", "unknown").lower()].append(t)

    side_stats = {}
    for side, items in by_side.items():
        w = sum(1 for i in items if i["outcome"] == "WIN")
        side_stats[side] = {
            "count":    len(items),
            "win_rate": w / len(items),
            "avg_pnl":  sum(float(i["pnl_pct"]) for i in items) / len(items),
        }

    # ── Rejim × Yön kombinasyonu ──────────────────────────────────────────
    combo: dict[str, list] = defaultdict(list)
    for t in trades:
        key = f"{t.get('regime','unknown')}+{t.get('side','?').lower()}"
        combo[key].append(t)

    combo_stats = {}
    for key, items in combo.items():
        if len(items) >= 3:  # en az 3 trade — istatistiksel anlamlılık için
            w = sum(1 for i in items if i["outcome"] == "WIN")
            combo_stats[key] = {
                "count":    len(items),
                "win_rate": w / len(items),
                "avg_pnl":  sum(float(i["pnl_pct"]) for i in items) / len(items),
            }

    # ── Kapanış sebebi analizi ────────────────────────────────────────────
    by_reason: dict[str, list] = defaultdict(list)
    for t in trades:
        by_reason[t.get("close_reason", "unknown")].append(t)

    reason_stats = {}
    for reason, items in by_reason.items():
        w = sum(1 for i in items if i["outcome"] == "WIN")
        reason_stats[reason] = {
            "count":    len(items),
            "win_rate": w / len(items),
            "avg_pnl":  sum(float(i["pnl_pct"]) for i in items) / len(items),
        }

    # ── Güven aralığı × kazanma oranı ────────────────────────────────────
    by_conf: dict[str, list] = defaultdict(list)
    for t in trades:
        by_conf[_bucket_confidence(float(t.get("confidence", 0.5)))].append(t)

    conf_stats = {}
    for bucket, items in by_conf.items():
        w = sum(1 for i in items if i["outcome"] == "WIN")
        conf_stats[bucket] = {
            "count":    len(items),
            "win_rate": w / len(items),
        }

    # ── Tutma süresi × kazanma oranı ─────────────────────────────────────
    by_hold: dict[str, list] = defaultdict(list)
    for t in trades:
        by_hold[_bucket_hold(int(t.get("hold_seconds", 0)))].append(t)

    hold_stats = {}
    for bucket, items in by_hold.items():
        w = sum(1 for i in items if i["outcome"] == "WIN")
        hold_stats[bucket] = {"count": len(items), "win_rate": w / len(items)}

    # ── En iyi / kötü semboller ───────────────────────────────────────────
    by_symbol: dict[str, list] = defaultdict(list)
    for t in trades:
        by_symbol[t.get("symbol", "?")].append(float(t["pnl_pct"]))

    sym_avg = {
        sym: sum(pnls) / len(pnls)
        for sym, pnls in by_symbol.items()
        if len(pnls) >= 2
    }
    best_syms  = sorted(sym_avg, key=lambda s: sym_avg[s], reverse=True)[:5]
    worst_syms = sorted(sym_avg, key=lambda s: sym_avg[s])[:5]

    return {
        "total":        total,
        "win_rate":     wins / total,
        "avg_pnl":      avg_pnl,
        "regime":       regime_stats,
        "side":         side_stats,
        "combo":        combo_stats,
        "close_reason": reason_stats,
        "confidence":   conf_stats,
        "hold":         hold_stats,
        "best_symbols": {s: round(sym_avg[s] * 100, 2) for s in best_syms},
        "worst_symbols":{s: round(sym_avg[s] * 100, 2) for s in worst_syms},
    }


def _stats_to_text(stats: dict, date_str: str) -> str:
    """
    İstatistik sözlüğünü LLM prompt'u için okunabilir metne çevir.
    """
    lines = [
        f"TRADE ANALİZİ ({date_str} — son {stats['total']} trade)",
        "",
        f"GENEL: {stats['total']} trade | "
        f"Kazanma: %{stats['win_rate']*100:.1f} | "
        f"Ort P&L: {stats['avg_pnl']*100:+.2f}%",
        "",
    ]

    # Rejim analizi
    if stats.get("regime"):
        lines.append("REJİM PERFORMANSI:")
        for reg, s in sorted(stats["regime"].items(), key=lambda x: -x[1]["count"]):
            flag = " ← ZAYIF" if s["win_rate"] < 0.45 else (" ← GÜÇLÜ" if s["win_rate"] > 0.60 else "")
            lines.append(
                f"  {reg}: {s['count']} trade | "
                f"%{s['win_rate']*100:.0f} kazanma | "
                f"ort {s['avg_pnl']*100:+.2f}%{flag}"
            )
        lines.append("")

    # Yön analizi
    if stats.get("side"):
        lines.append("YÖN PERFORMANSI:")
        for side, s in sorted(stats["side"].items(), key=lambda x: -x[1]["count"]):
            lines.append(
                f"  {side.upper()}: {s['count']} trade | "
                f"%{s['win_rate']*100:.0f} kazanma | "
                f"ort {s['avg_pnl']*100:+.2f}%"
            )
        lines.append("")

    # Rejim × Yön kombinasyonu
    if stats.get("combo"):
        lines.append("REJİM × YÖN KOMBİNASYONLARI:")
        for key, s in sorted(stats["combo"].items(), key=lambda x: x[1]["win_rate"]):
            flag = " ← KAÇIN" if s["win_rate"] < 0.40 else (" ← KULLAN" if s["win_rate"] > 0.65 else "")
            lines.append(
                f"  {key}: {s['count']} trade | "
                f"%{s['win_rate']*100:.0f} kazanma | "
                f"ort {s['avg_pnl']*100:+.2f}%{flag}"
            )
        lines.append("")

    # Kapanış sebebi
    if stats.get("close_reason"):
        lines.append("KAPANIS SEBEBİ ANALİZİ:")
        for reason, s in sorted(stats["close_reason"].items(), key=lambda x: -x[1]["count"]):
            lines.append(
                f"  {reason}: {s['count']} kez | "
                f"%{s['win_rate']*100:.0f} kazanma | "
                f"ort {s['avg_pnl']*100:+.2f}%"
            )
        lines.append("")

    # Güven aralıkları
    if stats.get("confidence"):
        lines.append("GÜVEN ARALIĞI × KAZANMA ORANI:")
        for bucket in ["0.45-0.55", "0.55-0.65", "0.65-0.75", "0.75+"]:
            s = stats["confidence"].get(bucket)
            if s:
                lines.append(
                    f"  Güven {bucket}: {s['count']} trade | "
                    f"%{s['win_rate']*100:.0f} kazanma"
                )
        lines.append("")

    # Tutma süresi
    if stats.get("hold"):
        lines.append("TUTMA SÜRESİ × KAZANMA ORANI:")
        for bucket in ["<15dk", "15-60dk", "1-4sa", ">4sa"]:
            s = stats["hold"].get(bucket)
            if s:
                lines.append(
                    f"  {bucket}: {s['count']} trade | "
                    f"%{s['win_rate']*100:.0f} kazanma"
                )
        lines.append("")

    # En iyi / kötü semboller
    if stats.get("best_symbols"):
        best = ", ".join(f"{s}({v:+.1f}%)" for s, v in stats["best_symbols"].items())
        lines.append(f"EN İYİ SEMBOLLER: {best}")
    if stats.get("worst_symbols"):
        worst = ", ".join(f"{s}({v:+.1f}%)" for s, v in stats["worst_symbols"].items())
        lines.append(f"EN KÖTÜ SEMBOLLER: {worst}")

    return "\n".join(lines)


# ── Belge üretimi ─────────────────────────────────────────────────────────────

async def _generate_strategy_doc(stats_text: str, date_str: str) -> str:
    """LLM ile somut alım satım kuralları belgesi üret."""
    prompt = f"""Sen bir kripto vadeli işlem sisteminin AI strateji analistisin.
Aşağıda gerçek trade geçmişinden çıkarılmış istatistikler var.
Bu verilere dayanarak somut, uygulanabilir alım satım kuralları yaz.

{stats_text}

Aşağıdaki formatta bir strateji belgesi oluştur (Türkçe):

## 1. KRİTİK KURALLAR (mutlaka uyulmalı)
- [veriye dayalı kural 1]
- [veriye dayalı kural 2]
- [veriye dayalı kural 3]

## 2. REJİM STRATEJİSİ
- [her rejim için ne yapılmalı / yapılmamalı]

## 3. POZİSYON BOYUTU
- [güven aralığına göre pozisyon önerisi]

## 4. ÇIKIŞ STRATEJİSİ
- [kapanış sebeplerinden öğrenilenler]

## 5. KAÇINILACAK DURUMLAR
- [kesinlikle açılmaması gereken kombinasyonlar]

Sadece verilerden desteklenen kurallar yaz. Spekülasyon yapma."""

    try:
        content, provider = await chat_completion(prompt, temperature=0.1, max_tokens=800)
        log.info(f"StrategyExtractor: belge üretildi [{provider}]")
        return content.strip()
    except Exception as e:
        log.warning(f"StrategyExtractor: LLM hatası — istatistik metni kaydediliyor: {e}")
        return stats_text   # LLM başarısız → ham istatistikleri kaydet


async def _save_strategy_doc(redis: aioredis.Redis, content: str, date_str: str, trade_count: int):
    """
    Strateji belgesini training:docs'a kaydet.
    Aynı prefix'e sahip eski AI belgeleri temizle (sadece son 3 tut).
    """
    docs_raw = await redis.get("training:docs")
    docs: list = json.loads(docs_raw) if docs_raw else []

    # Eski AI strateji belgelerini bul
    ai_docs  = [d for d in docs if d.get("title", "").startswith(STRATEGY_DOC_PREFIX)]
    other    = [d for d in docs if not d.get("title", "").startswith(STRATEGY_DOC_PREFIX)]

    # En fazla 3 eski AI belgesi tut
    ai_docs  = ai_docs[:2]

    new_doc = {
        "id":         f"ai_strategy_{int(time.time())}",
        "title":      f"{STRATEGY_DOC_PREFIX} — {date_str} ({trade_count} trade)",
        "content":    content,
        "source":     "ai_generated",
        "trade_count": trade_count,
        "created_at": time.time(),
    }

    docs = [new_doc] + ai_docs + other
    await redis.set("training:docs", json.dumps(docs))
    log.info(
        f"StrategyExtractor: '{new_doc['title']}' kaydedildi "
        f"— toplam {len(docs)} döküman aktif"
    )


# ── Ana döngü ─────────────────────────────────────────────────────────────────

async def strategy_extractor_loop(redis: aioredis.Redis):
    """
    Her saatte bir strateji belgesi üret.
    İlk çalıştırma: 5 dakika bekle (sistem ayağa kalksın, trade'ler birikisin).
    """
    log.info(
        f"StrategyExtractor başlatılıyor — "
        f"her {STRATEGY_INTERVAL_S//60} dakikada bir analiz, "
        f"min {MIN_TRADES_FOR_EXTRACT} trade gerekli"
    )
    await asyncio.sleep(300)   # 5 dakika ilk bekleme

    last_trade_count = 0

    while True:
        try:
            # Tüm lesson kategorilerini oku
            all_raws: list[str] = []

            # 1. Global trade dersleri (asıl kaynak)
            trade_raws = await redis.lrange("training:lessons", 0, MAX_LESSONS_TO_READ - 1)
            all_raws.extend(trade_raws)

            # 2. Sinyal kategorisi dersleri (regime bilgisi var)
            sig_raws = await redis.lrange("training:lessons:signals", 0, 49)
            all_raws.extend(sig_raws)

            # JSON parse
            lessons: list[dict] = []
            for r in all_raws:
                try:
                    lessons.append(json.loads(r))
                except Exception:
                    pass

            # Sadece gerçek trade'leri say (outcome = WIN/LOSS)
            actual_trades = [l for l in lessons if l.get("outcome") in ("WIN", "LOSS")]
            trade_count   = len(actual_trades)

            if trade_count < MIN_TRADES_FOR_EXTRACT:
                log.info(
                    f"StrategyExtractor: {trade_count} trade var, "
                    f"min {MIN_TRADES_FOR_EXTRACT} gerekli — atlandı"
                )
                await asyncio.sleep(STRATEGY_INTERVAL_S)
                continue

            # Yeni trade yoksa belge yenileme
            if trade_count == last_trade_count:
                log.debug("StrategyExtractor: yeni trade yok — atlandı")
                await asyncio.sleep(STRATEGY_INTERVAL_S)
                continue

            last_trade_count = trade_count
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

            log.info(f"StrategyExtractor: {trade_count} trade analiz ediliyor...")

            # İstatistik hesapla
            stats = _compute_stats(lessons)
            if not stats:
                await asyncio.sleep(STRATEGY_INTERVAL_S)
                continue

            stats_text = _stats_to_text(stats, date_str)
            log.debug(f"StrategyExtractor stats:\n{stats_text}")

            # LLM ile strateji belgesi üret
            doc_content = await _generate_strategy_doc(stats_text, date_str)

            # training:docs'a kaydet
            await _save_strategy_doc(redis, doc_content, date_str, trade_count)

            # Özet ders olarak da kaydet
            summary = (
                f"Strateji özeti ({date_str}): {trade_count} trade analiz edildi. "
                f"Genel kazanma oranı %{stats['win_rate']*100:.1f}, "
                f"ort P&L {stats['avg_pnl']*100:+.2f}%. "
                f"Strateji belgesi güncellendi."
            )
            await redis.lpush("training:lessons:strategy", json.dumps({
                "ts":          time.time(),
                "symbol":      "SYSTEM",
                "category":    "strategy",
                "trade_count": trade_count,
                "win_rate":    round(stats["win_rate"], 3),
                "avg_pnl":     round(stats["avg_pnl"], 4),
                "lesson":      summary,
            }))
            await redis.ltrim("training:lessons:strategy", 0, 9)

        except Exception as e:
            log.error(f"StrategyExtractor döngü hatası: {e}")

        await asyncio.sleep(STRATEGY_INTERVAL_S)
