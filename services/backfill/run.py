#!/usr/bin/env python3
"""
Prometheus Historical Backfill
================================
Downloads 30 days of 1h OHLCV klines for top N symbols from Binance FAPI,
runs 4 trading strategies, simulates paper trades, and writes results to:
  - Qdrant  → trade_memories collection (AI learns from historical wins/losses)
  - PostgreSQL → rule_genomes table (NEAT starts with evolved genome pool)

Run once:  docker compose run --rm backfill
"""

import asyncio
import hashlib
import json
import logging
import math
import os
import time
import urllib.request
import uuid
from datetime import datetime, timezone

import asyncpg
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
PG_DSN     = os.getenv("DATABASE_URL", "postgresql://prometheus:prometheus@postgres:5432/prometheus_trading")
DAYS       = int(os.getenv("BACKFILL_DAYS", "30"))
MAX_SYMS   = int(os.getenv("MAX_SYMBOLS", "50"))

# ── Binance REST ──────────────────────────────────────────────────────────────

def fetch_top_symbols(n: int) -> list[str]:
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        with urllib.request.urlopen(url, timeout=15) as r:
            tickers = json.loads(r.read())
        ranked = sorted(
            [t for t in tickers if t["symbol"].endswith("USDT")],
            key=lambda x: float(x.get("quoteVolume", 0)), reverse=True,
        )
        syms = [t["symbol"] for t in ranked[:n]]
        log.info(f"Fetched {len(syms)} top symbols from Binance")
        return syms
    except Exception as e:
        log.warning(f"Symbol fetch failed ({e}), using fallback list")
        return [
            "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
            "ADAUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","DOTUSDT",
            "MATICUSDT","UNIUSDT","ATOMUSDT","LTCUSDT","NEARUSDT",
            "FILUSDT","APTUSDT","ARBUSDT","OPUSDT","SUIUSDT",
        ]


def fetch_klines(symbol: str, days: int = 30) -> pd.DataFrame:
    """Download 1h klines for the last `days` days (Binance FAPI paginates by 1500)."""
    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3_600 * 1_000
    all_rows: list = []

    while start_ms < end_ms:
        url = (
            f"https://fapi.binance.com/fapi/v1/klines"
            f"?symbol={symbol}&interval=1h"
            f"&startTime={start_ms}&endTime={end_ms}&limit=1500"
        )
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                batch = json.loads(r.read())
        except Exception as e:
            log.warning(f"  klines page failed for {symbol}: {e}")
            break
        if not batch:
            break
        all_rows.extend(batch)
        start_ms = int(batch[-1][6]) + 1  # close_time of last candle + 1ms
        if len(batch) < 1500:
            break
        time.sleep(0.08)  # stay under rate limit

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_vol","trades","taker_base","taker_quote","ignore",
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for c in ("open","high","low","close","volume"):
        df[c] = df[c].astype(float)
    df = df.set_index("open_time").sort_index()
    return df[["open","high","low","close","volume"]]


# ── Feature engine ────────────────────────────────────────────────────────────

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()

    # RSI-14
    delta  = d["close"].diff()
    gain   = delta.clip(lower=0).rolling(14).mean()
    loss   = (-delta.clip(upper=0)).rolling(14).mean()
    d["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    # MACD (12/26/9)
    ema12          = d["close"].ewm(span=12, adjust=False).mean()
    ema26          = d["close"].ewm(span=26, adjust=False).mean()
    d["macd"]      = ema12 - ema26
    d["macd_sig"]  = d["macd"].ewm(span=9, adjust=False).mean()
    d["macd_hist"] = d["macd"] - d["macd_sig"]

    # Bollinger Bands (20,2)
    sma20          = d["close"].rolling(20).mean()
    std20          = d["close"].rolling(20).std()
    d["bb_upper"]  = sma20 + 2 * std20
    d["bb_lower"]  = sma20 - 2 * std20
    d["bb_pct"]    = (d["close"] - d["bb_lower"]) / (d["bb_upper"] - d["bb_lower"] + 1e-9)

    # EMA trend
    d["ema20"] = d["close"].ewm(span=20, adjust=False).mean()
    d["ema50"] = d["close"].ewm(span=50, adjust=False).mean()
    d["trend"] = np.where(d["ema20"] > d["ema50"], 1.0, -1.0)

    # ATR-14
    hl  = d["high"] - d["low"]
    hcp = (d["high"] - d["close"].shift()).abs()
    lcp = (d["low"]  - d["close"].shift()).abs()
    tr        = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    d["atr"]  = tr.rolling(14).mean()

    # Volume momentum
    d["vol_ratio"] = d["volume"] / (d["volume"].rolling(20).mean() + 1e-9)

    # Simple regime label
    ret5   = d["close"].pct_change(5)
    vol20  = d["close"].pct_change().rolling(20).std()
    d["regime"] = np.where(
        ret5.abs() > 1.5 * vol20,
        np.where(ret5 > 0, "trending_up", "trending_down"),
        np.where(vol20 > vol20.rolling(20).mean(), "volatile", "ranging"),
    )

    return d.dropna()


# ── Strategies (each = a genome archetype) ────────────────────────────────────

def sig_macd_cross(r, p) -> str:
    """MACD histogram zero-cross."""
    if p is None:
        return "flat"
    if p["macd_hist"] < 0 < r["macd_hist"] and r["rsi"] < 65:
        return "long"
    if p["macd_hist"] > 0 > r["macd_hist"] and r["rsi"] > 35:
        return "short"
    return "flat"


def sig_rsi_reversal(r, p) -> str:
    """RSI oversold/overbought + BB confirmation."""
    if r["rsi"] < 30 and r["bb_pct"] < 0.20:
        return "long"
    if r["rsi"] > 70 and r["bb_pct"] > 0.80:
        return "short"
    return "flat"


def sig_trend_follow(r, p) -> str:
    """EMA trend + MACD confirmation + volume surge."""
    if r["trend"] > 0 and r["macd_hist"] > 0 and r["vol_ratio"] > 1.3:
        return "long"
    if r["trend"] < 0 and r["macd_hist"] < 0 and r["vol_ratio"] > 1.3:
        return "short"
    return "flat"


def sig_bb_breakout(r, p) -> str:
    """Bollinger Band squeeze breakout."""
    if p is None:
        return "flat"
    if r["bb_pct"] > 0.95 and p["bb_pct"] < 0.85:
        return "long"
    if r["bb_pct"] < 0.05 and p["bb_pct"] > 0.15:
        return "short"
    return "flat"


STRATEGIES = {
    "macd_crossover":    sig_macd_cross,
    "rsi_mean_reversion": sig_rsi_reversal,
    "trend_follow":      sig_trend_follow,
    "bb_breakout":       sig_bb_breakout,
}


# ── Paper trade simulator ─────────────────────────────────────────────────────

def simulate_trades(symbol: str, df: pd.DataFrame, fn, name: str) -> list[dict]:
    trades: list[dict] = []
    in_trade   = False
    entry_px   = 0.0
    entry_idx  = 0
    direction  = "flat"
    entry_meta: dict = {}

    rows = df.reset_index()
    for i in range(50, len(rows)):
        row  = rows.iloc[i].to_dict()
        prev = rows.iloc[i - 1].to_dict() if i > 0 else None

        if not in_trade:
            sig = fn(row, prev)
            if sig in ("long", "short"):
                slip       = 0.0005
                entry_px   = float(row["close"]) * (1 + slip if sig == "long" else 1 - slip)
                direction  = sig
                entry_idx  = i
                entry_meta = {
                    "regime":      str(row.get("regime", "unknown")),
                    "rsi":         float(row.get("rsi", 50)),
                    "entry_time":  str(row.get("open_time", "")),
                }
                in_trade = True
        else:
            bars_held  = i - entry_idx
            cur_price  = float(row["close"])
            raw_pnl    = (cur_price - entry_px) / entry_px
            if direction == "short":
                raw_pnl = -raw_pnl

            should_exit = (
                raw_pnl <= -0.020 or  # stop-loss 2%
                raw_pnl >=  0.040 or  # take-profit 4%
                bars_held >= 8         # max hold 8 bars
            )

            if should_exit:
                slip     = 0.0005
                exit_px  = cur_price * (1 - slip if direction == "long" else 1 + slip)
                net_pnl  = (exit_px - entry_px) / entry_px
                if direction == "short":
                    net_pnl = -net_pnl
                net_pnl -= 0.001  # 0.1% round-trip fee

                reason = (
                    "stop_loss"   if raw_pnl <= -0.020 else
                    "take_profit" if raw_pnl >=  0.040 else
                    "timeout"
                )
                trades.append({
                    "symbol":        symbol,
                    "direction":     direction,
                    "entry_price":   entry_px,
                    "exit_price":    exit_px,
                    "pnl_pct":       net_pnl,
                    "was_winner":    net_pnl > 0,
                    "bars_held":     bars_held,
                    "entry_time":    entry_meta["entry_time"],
                    "regime":        entry_meta["regime"],
                    "rsi_at_entry":  entry_meta["rsi"],
                    "strategy":      name,
                    "exit_reason":   reason,
                    "error_category": reason if net_pnl < 0 else None,
                })
                in_trade = False

    return trades


# ── Fitness calculator ────────────────────────────────────────────────────────

def calc_fitness(trades: list[dict]) -> dict:
    if not trades:
        return {"fitness": 0.0, "win_rate": 0.0, "sharpe": 0.0, "max_dd": 0.0, "n": 0}

    pnls    = [t["pnl_pct"] for t in trades]
    win_rate = sum(1 for p in pnls if p > 0) / len(pnls)

    mean_p = float(np.mean(pnls))
    std_p  = float(np.std(pnls)) or 1e-9
    # 1h bars → √8760 annualisation
    sharpe = (mean_p / std_p) * math.sqrt(8760)

    equity   = np.cumprod([1 + p for p in pnls])
    roll_max = np.maximum.accumulate(equity)
    max_dd   = float(abs(min((equity - roll_max) / roll_max)))

    fitness = max(0.0, sharpe * win_rate * (1 - max_dd))

    return {"fitness": fitness, "win_rate": win_rate, "sharpe": sharpe, "max_dd": max_dd, "n": len(trades)}


# ── Qdrant helpers ────────────────────────────────────────────────────────────

def _qdrant(method: str, path: str, body=None) -> dict:
    url  = f"{QDRANT_URL}{path}"
    data = json.dumps(body).encode() if body else None
    hdrs = {"Content-Type": "application/json"} if body else {}
    req  = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        log.warning(f"Qdrant {method} {path}: {e}")
        return {}


def ensure_collection():
    res = _qdrant("GET", "/collections/trade_memories")
    if res.get("result"):
        log.info("Qdrant collection trade_memories already exists — appending")
        return
    _qdrant("PUT", "/collections/trade_memories", {
        "vectors": {"size": 64, "distance": "Cosine"},
    })
    log.info("Created Qdrant collection trade_memories")


def write_memories(trades: list[dict]):
    if not trades:
        return
    points = []
    for t in trades:
        # Deterministic pseudo-vector from trade fingerprint
        seed = int(hashlib.md5(json.dumps(t, default=str).encode()).hexdigest(), 16) % (2**31)
        rng  = np.random.RandomState(seed)
        vec  = rng.randn(64).tolist()

        points.append({
            "id":      str(uuid.uuid4()),
            "vector":  vec,
            "payload": {
                "symbol":         t["symbol"],
                "direction":      t["direction"],
                "pnl_pct":        t["pnl_pct"],
                "was_winner":     t["was_winner"],
                "regime":         t["regime"],
                "strategy":       t["strategy"],
                "exit_reason":    t["exit_reason"],
                "error_category": t.get("error_category"),
                "bars_held":      t["bars_held"],
                "rsi_at_entry":   t.get("rsi_at_entry", 50),
                "time":           t["entry_time"],
                "source":         "historical_backfill",
            },
        })

    for i in range(0, len(points), 100):
        _qdrant("PUT", "/collections/trade_memories/points", {"points": points[i:i+100]})

    log.info(f"  → {len(points)} memories upserted to Qdrant")


# ── PostgreSQL genome writer ──────────────────────────────────────────────────

async def write_genomes(conn, results: dict):
    """Insert/update genomes in rule_genomes table."""
    for genome_id, data in results.items():
        m   = data["metrics"]
        sym = data["symbol"]
        strat = data["strategy"]

        # Lifecycle status based on performance
        if m["fitness"] > 0.5 and m["win_rate"] > 0.55 and m["n"] >= 100:
            status = "ACTIVE"
        elif m["fitness"] > 0.2 and m["win_rate"] > 0.50 and m["n"] >= 50:
            status = "APPROVED"
        elif m["n"] > 0:
            status = "TRIAL"
        else:
            status = "DEAD"

        # Deterministic pseudo-topology
        h = int(hashlib.md5(f"{strat}{sym}".encode()).hexdigest(), 16)
        nodes = (h % 18) + 3
        conns = (h % 28) + 5

        regime_fit = {
            "trending_up":   round(m["win_rate"] * 1.2, 3),
            "trending_down": round(m["win_rate"] * 0.9, 3),
            "ranging":       round(m["win_rate"] * 0.8, 3),
            "volatile":      round(m["win_rate"] * 0.7, 3),
        }

        try:
            await conn.execute("""
                INSERT INTO rule_genomes
                    (genome_id, generation, species, status,
                     topology_nodes, topology_conns,
                     regime_fit,
                     win_rate, sharpe_ratio, max_drawdown,
                     total_trades, fitness_score,
                     born_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,$12, NOW())
                ON CONFLICT (genome_id) DO UPDATE SET
                    fitness_score = EXCLUDED.fitness_score,
                    win_rate      = EXCLUDED.win_rate,
                    sharpe_ratio  = EXCLUDED.sharpe_ratio,
                    status        = EXCLUDED.status,
                    total_trades  = EXCLUDED.total_trades
            """,
            genome_id, 1, strat, status,
            nodes, conns,
            json.dumps(regime_fit),
            m["win_rate"], m["sharpe"], m["max_dd"],
            m["n"], m["fitness"],
            )
        except Exception as e:
            log.warning(f"  genome insert failed ({genome_id}): {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    log.info("=" * 60)
    log.info("  PROMETHEUS HISTORICAL BACKFILL")
    log.info(f"  {DAYS} days · {MAX_SYMS} symbols · 4 strategies")
    log.info("=" * 60)

    symbols = fetch_top_symbols(MAX_SYMS)
    ensure_collection()

    try:
        conn = await asyncpg.connect(PG_DSN)
        log.info("Connected to PostgreSQL")
    except Exception as e:
        log.warning(f"PostgreSQL unavailable ({e}) — will skip genome writes")
        conn = None

    all_trades:   list[dict] = []
    genome_pool:  dict       = {}
    failed_syms:  list[str]  = []

    for idx, sym in enumerate(symbols):
        log.info(f"[{idx+1:3d}/{len(symbols)}] {sym}")

        df = fetch_klines(sym, days=DAYS)
        if df.empty or len(df) < 60:
            log.warning(f"  insufficient data ({len(df)} bars) — skip")
            failed_syms.append(sym)
            continue

        df_feat = compute_features(df)
        if len(df_feat) < 50:
            failed_syms.append(sym)
            continue

        for strat_name, strat_fn in STRATEGIES.items():
            trades  = simulate_trades(sym, df_feat, strat_fn, strat_name)
            metrics = calc_fitness(trades)

            gid = f"hist_{strat_name}_{sym.lower()}_{hashlib.md5(f'{strat_name}{sym}'.encode()).hexdigest()[:8]}"
            genome_pool[gid] = {"symbol": sym, "strategy": strat_name, "metrics": metrics}
            all_trades.extend(trades)

            log.info(
                f"  {strat_name:<22} {len(trades):4d} trades | "
                f"WR={metrics['win_rate']:.0%} | "
                f"Sharpe={metrics['sharpe']:+.2f} | "
                f"Fitness={metrics['fitness']:.4f}"
            )

        time.sleep(0.25)  # Binance rate limit courtesy

    # ── Write to Qdrant ──
    log.info(f"\nWriting {len(all_trades):,} memories to Qdrant...")
    write_memories(all_trades)

    # ── Write to PostgreSQL ──
    if conn:
        log.info(f"Writing {len(genome_pool)} genomes to PostgreSQL...")
        await write_genomes(conn, genome_pool)
        await conn.close()

    # ── Summary ──────────────────────────────────────────────────────────────
    total_n  = len(all_trades)
    winners  = sum(1 for t in all_trades if t["was_winner"])
    overall_wr = winners / total_n if total_n else 0

    top5 = sorted(genome_pool.values(), key=lambda x: x["metrics"]["fitness"], reverse=True)[:5]

    log.info("\n" + "=" * 60)
    log.info("  BACKFILL COMPLETE")
    log.info("=" * 60)
    log.info(f"  Symbols processed : {len(symbols) - len(failed_syms)}/{len(symbols)}")
    log.info(f"  Total trades      : {total_n:,}")
    log.info(f"  Overall win rate  : {overall_wr:.1%}")
    log.info(f"  Qdrant memories   : {total_n:,}")
    log.info(f"  PostgreSQL genomes: {len(genome_pool)}")
    if failed_syms:
        log.info(f"  Skipped symbols   : {', '.join(failed_syms)}")
    log.info("\n  Top 5 Genomes by Fitness:")
    for g in top5:
        m = g["metrics"]
        log.info(
            f"    {g['strategy']:<22} on {g['symbol']:<12} "
            f"fitness={m['fitness']:.4f}  WR={m['win_rate']:.0%}  "
            f"Sharpe={m['sharpe']:+.2f}  ({m['n']} trades)"
        )
    log.info("=" * 60)
    log.info("  Dashboard → AI Memory page will now show full history.")
    log.info("  NEAT evolution starts from a warm genome pool.")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
