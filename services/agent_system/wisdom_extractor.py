"""
Wisdom Extractor — PostgreSQL'deki TÜM trade geçmişini okur,
sıkıştırılmış örüntüler çıkarır, Redis'e yazar.
60 dakikada bir çalışır. LLM yok — saf matematik.
Sistem hiç unutmaz: 1 trade veya 100.000 trade aynı şekilde analiz edilir.
"""
import asyncio
import json
import logging
import os
import time

import asyncpg
import redis.asyncio as aioredis

log = logging.getLogger(__name__)

REDIS_URL        = os.getenv("REDIS_URL", "redis://redis:6379")
EXTRACT_INTERVAL = 3600  # 60 dakikada bir

DB_CONFIG = dict(
    host     = os.getenv("POSTGRES_HOST",     "postgres"),
    port     = int(os.getenv("POSTGRES_PORT", "5432")),
    database = os.getenv("POSTGRES_DB",       "prometheus_trading"),
    user     = os.getenv("POSTGRES_USER",     "prometheus"),
    password = os.getenv("POSTGRES_PASSWORD", "prometheus123"),
    command_timeout = 30,
)


async def _extract(conn: asyncpg.Connection) -> dict:
    """Tüm trades tablosunu sorgula — saf SQL aggregation."""
    wisdom: dict = {}

    total = await conn.fetchval("SELECT COUNT(*) FROM trades")
    wisdom["total_trades"] = int(total or 0)
    if wisdom["total_trades"] == 0:
        return wisdom

    # Genel kazanma oranı
    wr = await conn.fetchval(
        "SELECT AVG(CASE WHEN pnl_pct > 0 THEN 1.0 ELSE 0.0 END) FROM trades"
    )
    wisdom["overall_win_rate"] = round(float(wr or 0), 4)

    # Rejim × Yön kalıpları (tam rejim ismi JSONB'den)
    rows = await conn.fetch("""
        SELECT
            COALESCE(autopsy_result->>'regime', regime_at_entry, 'unknown') AS regime,
            side,
            COUNT(*)                                                          AS total,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END)                    AS wins,
            ROUND(AVG(pnl_pct)::numeric * 100, 2)                            AS avg_pnl,
            ROUND(STDDEV(pnl_pct)::numeric * 100, 2)                         AS std_pnl
        FROM trades
        WHERE side IS NOT NULL
        GROUP BY 1, 2
        HAVING COUNT(*) >= 3
        ORDER BY COUNT(*) DESC
    """)
    wisdom["regime_patterns"] = [
        {
            "regime":      r["regime"],
            "side":        r["side"],
            "total":       int(r["total"]),
            "win_rate_pct": round(float(r["wins"]) / float(r["total"]) * 100, 1),
            "avg_pnl_pct": float(r["avg_pnl"] or 0),
        }
        for r in rows
    ]

    # Kapanış nedeni analizi
    reason_rows = await conn.fetch("""
        SELECT
            COALESCE(autopsy_result->>'close_reason', 'unknown') AS reason,
            COUNT(*)                                               AS total,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END)        AS wins,
            ROUND(AVG(pnl_pct)::numeric * 100, 2)                AS avg_pnl
        FROM trades
        WHERE autopsy_result IS NOT NULL
        GROUP BY 1
        HAVING COUNT(*) >= 3
        ORDER BY COUNT(*) DESC
    """)
    wisdom["by_close_reason"] = [
        {
            "reason":      r["reason"],
            "total":       int(r["total"]),
            "win_rate_pct": round(float(r["wins"]) / float(r["total"]) * 100, 1),
            "avg_pnl_pct": float(r["avg_pnl"] or 0),
        }
        for r in reason_rows
    ]

    # Güven bandı analizi
    conf_rows = await conn.fetch("""
        SELECT
            CASE
                WHEN confidence < 0.72 THEN '0.70-0.72'
                WHEN confidence < 0.75 THEN '0.72-0.75'
                WHEN confidence < 0.80 THEN '0.75-0.80'
                ELSE '0.80+'
            END                                                   AS band,
            COUNT(*)                                               AS total,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END)        AS wins,
            ROUND(AVG(pnl_pct)::numeric * 100, 2)                AS avg_pnl
        FROM trades
        WHERE confidence >= 0.70
        GROUP BY 1
        HAVING COUNT(*) >= 3
        ORDER BY 1
    """)
    wisdom["by_confidence"] = [
        {
            "band":        r["band"],
            "total":       int(r["total"]),
            "win_rate_pct": round(float(r["wins"]) / float(r["total"]) * 100, 1),
            "avg_pnl_pct": float(r["avg_pnl"] or 0),
        }
        for r in conf_rows
    ]

    # En iyi / en kötü coinler
    sym_rows = await conn.fetch("""
        SELECT
            symbol,
            COUNT(*)                                               AS total,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END)        AS wins,
            ROUND(AVG(pnl_pct)::numeric * 100, 2)                AS avg_pnl
        FROM trades
        GROUP BY symbol
        HAVING COUNT(*) >= 5
        ORDER BY AVG(pnl_pct) DESC
    """)
    sym_list = [
        {
            "symbol":      r["symbol"],
            "total":       int(r["total"]),
            "win_rate_pct": round(float(r["wins"]) / float(r["total"]) * 100, 1),
            "avg_pnl_pct": float(r["avg_pnl"] or 0),
        }
        for r in sym_rows
    ]
    wisdom["best_symbols"]  = sym_list[:10]
    wisdom["worst_symbols"] = sym_list[-10:] if len(sym_list) > 10 else []
    wisdom["extracted_at"]  = time.time()
    return wisdom


def _to_text(wisdom: dict) -> str:
    """Wisdom dict → Ollama için okunabilir metin."""
    total = wisdom.get("total_trades", 0)
    if total == 0:
        return ""

    wr = wisdom.get("overall_win_rate", 0) * 100
    lines = [
        f"=== TARİHSEL TRADE ANALİZİ ({total} trade) ===",
        f"Genel kazanma oranı: %{wr:.1f}",
        "",
        "--- REJİM × YÖN KALIPLARI (iyi → kötü) ---",
    ]

    for p in sorted(wisdom.get("regime_patterns", []), key=lambda x: x["win_rate_pct"], reverse=True):
        verdict = "✓ AÇ" if p["win_rate_pct"] > 52 else "✗ AÇMA"
        lines.append(
            f"{verdict}  {p['regime']:12s} {p['side'].upper():5s} → "
            f"%{p['win_rate_pct']:.0f} kazanç, ort {p['avg_pnl_pct']:+.2f}%  ({p['total']} trade)"
        )

    if wisdom.get("by_confidence"):
        lines += ["", "--- GÜVEN BANDI ANALİZİ ---"]
        for c in wisdom["by_confidence"]:
            lines.append(
                f"  conf {c['band']}: %{c['win_rate_pct']:.0f} kazanç, "
                f"ort {c['avg_pnl_pct']:+.2f}%  ({c['total']} trade)"
            )

    if wisdom.get("by_close_reason"):
        lines += ["", "--- KAPANIŞ NEDENİ ANALİZİ ---"]
        for r in wisdom["by_close_reason"]:
            lines.append(
                f"  {r['reason']:12s}: %{r['win_rate_pct']:.0f} kazanç, "
                f"ort {r['avg_pnl_pct']:+.2f}%  ({r['total']} trade)"
            )

    best = [s for s in wisdom.get("best_symbols", []) if s["avg_pnl_pct"] > 0][:5]
    if best:
        lines += ["", "--- EN İYİ 5 COIN ---"]
        for s in best:
            lines.append(f"  {s['symbol']:12s}: %{s['win_rate_pct']:.0f} kazanç, ort {s['avg_pnl_pct']:+.2f}%  ({s['total']} trade)")

    worst = [s for s in wisdom.get("worst_symbols", []) if s["avg_pnl_pct"] < 0][:5]
    if worst:
        lines += ["", "--- KAÇINILACAK 5 COIN ---"]
        for s in worst:
            lines.append(f"  {s['symbol']:12s}: %{s['win_rate_pct']:.0f} kazanç, ort {s['avg_pnl_pct']:+.2f}%  ({s['total']} trade) ← AÇMA")

    return "\n".join(lines)


async def wisdom_extractor_loop(redis_url: str):
    """60 dakikada bir PostgreSQL'den tüm geçmişi oku, Redis'e yaz."""
    redis = await aioredis.from_url(redis_url)
    log.info("[WisdomExtractor] Başlatıldı — 60 dakikada bir çalışacak")

    while True:
        try:
            conn = await asyncpg.connect(**DB_CONFIG)
            try:
                wisdom = await _extract(conn)
                total = wisdom.get("total_trades", 0)
                if total > 0:
                    await redis.set("wisdom:patterns", json.dumps(wisdom), ex=7200)
                    await redis.set("wisdom:text",     _to_text(wisdom),   ex=7200)
                    log.info(
                        f"[WisdomExtractor] {total} trade analiz edildi — "
                        f"{len(wisdom.get('regime_patterns', []))} rejim kalıbı çıkarıldı"
                    )
                else:
                    log.debug("[WisdomExtractor] PostgreSQL'de henüz trade yok")
            finally:
                await conn.close()
        except Exception as e:
            log.warning(f"[WisdomExtractor] hata: {e}")

        await asyncio.sleep(EXTRACT_INTERVAL)
