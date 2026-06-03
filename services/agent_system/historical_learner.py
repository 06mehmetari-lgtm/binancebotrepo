"""
Historical Learner — 500 coin × 30 günlük 1h OHLCV çeker, her coin için
"neden yükselir / neden düşer" analizi yapar, Redis + PostgreSQL'e yazar.
Başlangıçta bir kez, sonra her 24 saatte bir çalışır.

Çıktı:
  Redis  → coin:history:{symbol}  (JSON, TTL 25 saat)
  Redis  → coin:history:summary   (tüm coinlerin özeti)
  PG     → coin_patterns tablosu  (kalıcı)

Signal engine bu veriyi okuyarak confidence'ı ayarlar.
Ollama trainer bu veriyi okuyarak modeli eğitir.
"""
import asyncio
import json
import logging
import os
import time
from typing import Optional

import aiohttp
import asyncpg
import numpy as np
import redis.asyncio as aioredis

log = logging.getLogger(__name__)

REDIS_URL   = os.getenv("REDIS_URL", "redis://redis:6379")
BINANCE_URL = "https://fapi.binance.com"
INTERVAL    = "1h"
DAYS        = 30
LOOKAHEAD   = 4      # 4 saat sonrasına bak
WIN_PCT     = 0.015  # %1.5 hareketi "kazanç" say
MIN_SAMPLES = 8      # pattern için min örnek
RUN_INTERVAL = 86400 # 24 saatte bir

DB_CONFIG = dict(
    host     = os.getenv("POSTGRES_HOST",     "postgres"),
    port     = int(os.getenv("POSTGRES_PORT", "5432")),
    database = os.getenv("POSTGRES_DB",       "prometheus_trading"),
    user     = os.getenv("POSTGRES_USER",     "prometheus"),
    password = os.getenv("POSTGRES_PASSWORD", "prometheus123"),
    command_timeout = 30,
)

LIMIT = DAYS * 24  # ~720 mum


# ── Binance veri çekme ──────────────────────────────────────────────────────

async def _fetch_klines(
    session: aiohttp.ClientSession,
    symbol: str,
    semaphore: asyncio.Semaphore,
) -> Optional[np.ndarray]:
    """
    1h OHLCV → ndarray shape (N, 6): [ts, open, high, low, close, volume]
    """
    async with semaphore:
        url = f"{BINANCE_URL}/fapi/v1/klines"
        params = {"symbol": symbol, "interval": INTERVAL, "limit": min(LIMIT, 1500)}
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                raw = await resp.json()
                if not raw:
                    return None
                arr = np.array(
                    [[float(c[0]), float(c[1]), float(c[2]),
                      float(c[3]), float(c[4]), float(c[5])]
                     for c in raw],
                    dtype=np.float64,
                )
                return arr
        except Exception as e:
            log.debug(f"[HistLearner] kline fetch {symbol}: {e}")
            return None


# ── İndikatör hesaplama (saf numpy) ─────────────────────────────────────────

def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(close, prepend=close[0])
    gain  = np.where(delta > 0, delta, 0.0)
    loss  = np.where(delta < 0, -delta, 0.0)
    alpha = 1 / period
    avg_g = np.zeros_like(close)
    avg_l = np.zeros_like(close)
    avg_g[period] = np.mean(gain[1:period+1])
    avg_l[period] = np.mean(loss[1:period+1])
    for i in range(period + 1, len(close)):
        avg_g[i] = alpha * gain[i] + (1 - alpha) * avg_g[i-1]
        avg_l[i] = alpha * loss[i] + (1 - alpha) * avg_l[i-1]
    rs = np.where(avg_l > 0, avg_g / avg_l, 100.0)
    return np.where(avg_l == 0, 100.0, 100 - 100 / (1 + rs))


def _ema(arr: np.ndarray, span: int) -> np.ndarray:
    alpha = 2 / (span + 1)
    out = np.zeros_like(arr)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i-1]
    return out


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low,
         np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return _ema(tr, period)


def _compute_features(arr: np.ndarray) -> dict:
    """OHLCV ndarray → indikatör dizileri sözlüğü."""
    close  = arr[:, 4]
    high   = arr[:, 2]
    low    = arr[:, 3]
    volume = arr[:, 5]

    ema20  = _ema(close, 20)
    ema50  = _ema(close, 50)
    ema200 = _ema(close, 200)
    macd_line   = _ema(close, 12) - _ema(close, 26)
    macd_signal = _ema(macd_line, 9)
    macd_hist   = macd_line - macd_signal
    atr_arr     = _atr(high, low, close, 14)
    rsi_arr     = _rsi(close, 14)

    vol_sma20 = np.convolve(volume, np.ones(20)/20, mode='full')[:len(volume)]
    vol_ratio = np.where(vol_sma20 > 0, volume / vol_sma20, 1.0)

    # Bollinger
    sma20 = np.convolve(close, np.ones(20)/20, mode='full')[:len(close)]
    std20 = np.array([np.std(close[max(0,i-19):i+1]) for i in range(len(close))])
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    bb_pos   = np.where(bb_upper > bb_lower, (close - bb_lower) / (bb_upper - bb_lower), 0.5)

    return {
        "close": close, "high": high, "low": low, "volume": volume,
        "ema20": ema20, "ema50": ema50, "ema200": ema200,
        "macd_hist": macd_hist, "rsi": rsi_arr,
        "atr": atr_arr, "vol_ratio": vol_ratio, "bb_pos": bb_pos,
    }


# ── Pattern analizi ──────────────────────────────────────────────────────────

def _indicator_state(feat: dict, i: int) -> str:
    """İ. adımındaki indikatör durumunu kategorik string'e dönüştür."""
    rsi = feat["rsi"][i]
    if rsi < 30:       rsi_cat = "RSI_OS"   # oversold
    elif rsi < 45:     rsi_cat = "RSI_LOW"
    elif rsi < 55:     rsi_cat = "RSI_NEU"
    elif rsi < 70:     rsi_cat = "RSI_HIGH"
    else:              rsi_cat = "RSI_OB"   # overbought

    macd = feat["macd_hist"][i]
    prev = feat["macd_hist"][i-1] if i > 0 else macd
    if macd > 0 and macd > prev:   macd_cat = "MACD_UP"
    elif macd > 0:                  macd_cat = "MACD_POS"
    elif macd < 0 and macd < prev:  macd_cat = "MACD_DN"
    else:                           macd_cat = "MACD_NEG"

    ema_cat = "EMA_BULL" if feat["ema20"][i] > feat["ema50"][i] else "EMA_BEAR"

    vol = feat["vol_ratio"][i]
    if vol > 2.0:      vol_cat = "VOL_HIGH"
    elif vol > 1.3:    vol_cat = "VOL_MED"
    else:              vol_cat = "VOL_LOW"

    bb = feat["bb_pos"][i]
    if bb < 0.20:      bb_cat = "BB_BOT"
    elif bb > 0.80:    bb_cat = "BB_TOP"
    else:              bb_cat = "BB_MID"

    return f"{rsi_cat}|{macd_cat}|{ema_cat}|{vol_cat}|{bb_cat}"


def _analyze_coin(arr: np.ndarray, symbol: str) -> dict:
    """
    30 günlük 1h veriden coin analizi çıkar.
    Her mum için: indikatör durumu → 4h sonraki hareket → WIN/LOSS
    """
    if len(arr) < 100:
        return {}

    feat = _compute_features(arr)
    close = feat["close"]
    n = len(close)

    # Her mum için state ve 4h sonraki sonucu hesapla
    state_outcomes: dict[str, dict] = {}  # state → {long_w, long_n, short_w, short_n}

    for i in range(50, n - LOOKAHEAD):  # ilk 50 mumu ısınma için atla
        future_ret = (close[i + LOOKAHEAD] - close[i]) / close[i]
        long_win   = future_ret >  WIN_PCT
        short_win  = future_ret < -WIN_PCT

        state = _indicator_state(feat, i)
        so = state_outcomes.setdefault(state, {"lw": 0, "ln": 0, "sw": 0, "sn": 0})
        so["ln"] += 1
        so["sn"] += 1
        if long_win:  so["lw"] += 1
        if short_win: so["sw"] += 1

    # En iyi long ve short pattern'ları bul
    long_patterns  = []
    short_patterns = []

    for state, so in state_outcomes.items():
        if so["ln"] < MIN_SAMPLES:
            continue
        l_wr = so["lw"] / so["ln"]
        s_wr = so["sw"] / so["sn"]
        parts = state.split("|")

        if l_wr > 0.50:
            long_patterns.append({
                "conditions": state,
                "rsi": parts[0], "macd": parts[1], "ema": parts[2],
                "vol": parts[3], "bb": parts[4],
                "win_rate": round(l_wr, 3),
                "sample": so["ln"],
                "score": round(l_wr * min(so["ln"] / 20, 1.0), 3),
            })
        if s_wr > 0.50:
            short_patterns.append({
                "conditions": state,
                "rsi": parts[0], "macd": parts[1], "ema": parts[2],
                "vol": parts[3], "bb": parts[4],
                "win_rate": round(s_wr, 3),
                "sample": so["sn"],
                "score": round(s_wr * min(so["sn"] / 20, 1.0), 3),
            })

    long_patterns.sort(key=lambda x: x["score"], reverse=True)
    short_patterns.sort(key=lambda x: x["score"], reverse=True)

    # Mevcut indikatör durumu (son mum)
    current_state = _indicator_state(feat, n - 1)
    current_so    = state_outcomes.get(current_state, {})
    hist_long_wr  = round(current_so.get("lw", 0) / max(current_so.get("ln", 1), 1), 3)
    hist_short_wr = round(current_so.get("sw", 0) / max(current_so.get("sn", 1), 1), 3)

    # Genel istatistikler
    total_candles = n - 50 - LOOKAHEAD
    all_long_wins = sum(so["lw"] for so in state_outcomes.values())
    all_long_n    = sum(so["ln"] for so in state_outcomes.values())
    all_short_wins= sum(so["sw"] for so in state_outcomes.values())
    all_short_n   = sum(so["sn"] for so in state_outcomes.values())

    overall_long_wr  = round(all_long_wins  / max(all_long_n,  1), 3)
    overall_short_wr = round(all_short_wins / max(all_short_n, 1), 3)

    # Momentum skoru (-1 → +1): negatif = ayı, pozitif = boğa
    rsi_now    = feat["rsi"][-1]
    macd_now   = feat["macd_hist"][-1]
    ema_bull   = 1.0 if feat["ema20"][-1] > feat["ema50"][-1] else -1.0
    rsi_score  = (rsi_now - 50) / 50  # -1 to +1
    macd_norm  = np.tanh(macd_now / (feat["atr"][-1] + 1e-8) * 10)
    momentum   = round((rsi_score * 0.35 + macd_norm * 0.40 + ema_bull * 0.25), 3)

    # Son 30 günde günlük volatilite
    daily_returns = np.diff(close[::24]) / close[:-1:24] if len(close) >= 48 else np.array([0.01])
    avg_daily_vol = round(float(np.std(daily_returns)) * 100, 3)

    return {
        "symbol":           symbol,
        "analyzed_candles": total_candles,
        "overall_long_wr":  overall_long_wr,
        "overall_short_wr": overall_short_wr,
        "best_long_patterns":  long_patterns[:10],
        "best_short_patterns": short_patterns[:10],
        "current_state":       current_state,
        "current_hist_long_wr":  hist_long_wr,
        "current_hist_short_wr": hist_short_wr,
        "momentum_score":   momentum,
        "avg_daily_vol_pct": avg_daily_vol,
        "analyzed_at":      time.time(),
    }


def _make_text_summary(analysis: dict) -> str:
    """Ollama için okunabilir metin özeti."""
    sym  = analysis["symbol"]
    lwr  = analysis["overall_long_wr"]
    swr  = analysis["overall_short_wr"]
    mom  = analysis["momentum_score"]
    vol  = analysis["avg_daily_vol_pct"]
    cur_l = analysis["current_hist_long_wr"]
    cur_s = analysis["current_hist_short_wr"]

    lines = [f"{sym}: LONG %{lwr*100:.0f} | SHORT %{swr*100:.0f} | Mom={mom:+.2f} | Günlük vol={vol:.1f}%"]
    lines.append(f"  Mevcut durum ({analysis['current_state'][:30]}): LONG %{cur_l*100:.0f} / SHORT %{cur_s*100:.0f}")

    for p in analysis["best_long_patterns"][:3]:
        lines.append(f"  ✓LONG  {p['rsi']}+{p['macd']}+{p['ema']}+{p['vol']} → %{p['win_rate']*100:.0f} (n={p['sample']})")
    for p in analysis["best_short_patterns"][:3]:
        lines.append(f"  ✓SHORT {p['rsi']}+{p['macd']}+{p['ema']}+{p['vol']} → %{p['win_rate']*100:.0f} (n={p['sample']})")

    return "\n".join(lines)


# ── DB/Redis yazma ────────────────────────────────────────────────────────────

async def _ensure_table(pool: asyncpg.Pool):
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS coin_patterns (
            symbol       VARCHAR(20) PRIMARY KEY,
            patterns     JSONB       NOT NULL,
            computed_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)


async def _write_db(pool: asyncpg.Pool, symbol: str, analysis: dict):
    try:
        await pool.execute("""
            INSERT INTO coin_patterns (symbol, patterns, computed_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (symbol) DO UPDATE
              SET patterns = EXCLUDED.patterns,
                  computed_at = NOW()
        """, symbol, json.dumps(analysis))
    except Exception as e:
        log.debug(f"[HistLearner] DB write {symbol}: {e}")


# ── Ana döngü ─────────────────────────────────────────────────────────────────

async def _run_once(redis: aioredis.Redis, db_pool: Optional[asyncpg.Pool]):
    """500 coini çek, analiz et, yaz."""
    t0 = time.time()

    # Aktif sembolleri Redis'ten al
    raw_keys = await redis.keys("features:latest:*")
    symbols = sorted(set(
        (k.decode() if isinstance(k, bytes) else k).replace("features:latest:", "").upper()
        for k in raw_keys
    ))
    if not symbols:
        log.warning("[HistLearner] Henüz features yok, 60s sonra tekrar denenecek")
        return

    log.info(f"[HistLearner] {len(symbols)} coin analiz ediliyor ({DAYS} gün, {INTERVAL})...")

    semaphore = asyncio.Semaphore(20)  # eş zamanlı max 20 istek
    analyses: list[dict] = []
    errors = 0

    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_klines(session, sym, semaphore) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for sym, arr in zip(symbols, results):
        if isinstance(arr, Exception) or arr is None:
            errors += 1
            continue
        try:
            analysis = _analyze_coin(arr, sym)
            if not analysis:
                continue
            analyses.append(analysis)

            # Redis'e yaz (TTL 25 saat)
            await redis.set(
                f"coin:history:{sym}",
                json.dumps(analysis),
                ex=90000,
            )
            # DB'ye yaz
            if db_pool:
                await _write_db(db_pool, sym, analysis)
        except Exception as e:
            log.debug(f"[HistLearner] analiz {sym}: {e}")
            errors += 1

    if not analyses:
        log.warning("[HistLearner] Hiç analiz üretilemedi")
        return

    # Özet istatistik
    avg_lwr = round(sum(a["overall_long_wr"]  for a in analyses) / len(analyses), 3)
    avg_swr = round(sum(a["overall_short_wr"] for a in analyses) / len(analyses), 3)
    top_long  = sorted(analyses, key=lambda a: a["overall_long_wr"],  reverse=True)[:20]
    top_short = sorted(analyses, key=lambda a: a["overall_short_wr"], reverse=True)[:20]
    bullish_coins = [a["symbol"] for a in analyses if a["momentum_score"] > 0.3]
    bearish_coins = [a["symbol"] for a in analyses if a["momentum_score"] < -0.3]

    summary = {
        "coin_count":     len(analyses),
        "errors":         errors,
        "avg_long_wr":    avg_lwr,
        "avg_short_wr":   avg_swr,
        "bullish_coins":  bullish_coins[:50],
        "bearish_coins":  bearish_coins[:50],
        "top_long_coins":  [{"symbol": a["symbol"], "long_wr": a["overall_long_wr"]} for a in top_long],
        "top_short_coins": [{"symbol": a["symbol"], "short_wr": a["overall_short_wr"]} for a in top_short],
        "computed_at": time.time(),
    }
    await redis.set("coin:history:summary", json.dumps(summary), ex=90000)

    # Ollama için metin özeti (top 100 coin)
    top100 = sorted(analyses, key=lambda a: a["analyzed_candles"], reverse=True)[:100]
    wisdom_lines = [
        f"=== {DAYS} GÜNLÜK TARİHSEL ANALİZ ({len(analyses)} coin) ===",
        f"Ortalama LONG kazanma: %{avg_lwr*100:.0f} | SHORT kazanma: %{avg_swr*100:.0f}",
        f"Boğa momentumu: {len(bullish_coins)} coin | Ayı momentumu: {len(bearish_coins)} coin",
        "",
        "--- MEVCUT DURUMDA EN İYİ LONG COINLER ---",
    ]
    for a in sorted(analyses, key=lambda x: x["current_hist_long_wr"], reverse=True)[:15]:
        if a["current_hist_long_wr"] > 0.55:
            wisdom_lines.append(
                f"  {a['symbol']:15s} LONG %{a['current_hist_long_wr']*100:.0f} "
                f"(mom={a['momentum_score']:+.2f}, vol={a['avg_daily_vol_pct']:.1f}%)"
            )
    wisdom_lines += ["", "--- MEVCUT DURUMDA EN İYİ SHORT COINLER ---"]
    for a in sorted(analyses, key=lambda x: x["current_hist_short_wr"], reverse=True)[:15]:
        if a["current_hist_short_wr"] > 0.55:
            wisdom_lines.append(
                f"  {a['symbol']:15s} SHORT %{a['current_hist_short_wr']*100:.0f} "
                f"(mom={a['momentum_score']:+.2f}, vol={a['avg_daily_vol_pct']:.1f}%)"
            )

    wisdom_lines += ["", "--- TOP 100 COİN DETAYLI PATTERN ANALİZİ ---"]
    for a in top100:
        wisdom_lines.append(_make_text_summary(a))

    await redis.set("coin:history:text", "\n".join(wisdom_lines), ex=90000)

    elapsed = round(time.time() - t0, 1)
    log.info(
        f"[HistLearner] Tamamlandı: {len(analyses)} coin analiz edildi, "
        f"{errors} hata, {elapsed}s | "
        f"Boğa:{len(bullish_coins)} Ayı:{len(bearish_coins)}"
    )


async def historical_learner_loop(redis_url: str):
    """Başlangıçta ve 24 saatte bir çalışır."""
    redis = await aioredis.from_url(redis_url)

    db_pool: Optional[asyncpg.Pool] = None
    try:
        db_pool = await asyncpg.create_pool(**DB_CONFIG, min_size=1, max_size=3)
        await _ensure_table(db_pool)
        log.info("[HistLearner] PostgreSQL bağlantısı kuruldu")
    except Exception as e:
        log.warning(f"[HistLearner] PostgreSQL yok, sadece Redis'e yazacak: {e}")

    await asyncio.sleep(60)  # diğer servisler başlasın

    while True:
        try:
            await _run_once(redis, db_pool)
        except Exception as e:
            log.error(f"[HistLearner] döngü hatası: {e}")
        await asyncio.sleep(RUN_INTERVAL)
