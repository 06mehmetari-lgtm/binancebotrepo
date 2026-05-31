"""
Backtest service — runs once on startup (or if results are stale),
saves results to Redis, then sleeps until next run.

Fetches 1 year of Binance Futures 1h klines for top symbols,
runs the same signal logic as signal_generator.py (technical mode),
simulates paper trades with ATR stops, computes full portfolio metrics.
"""
import asyncio
import json
import logging
import os
import time

import numpy as np
import redis.asyncio as aioredis

from historical_fetcher import fetch_klines, fetch_top_symbols
from backtest_engine import BacktestEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
BACKTEST_SYMBOLS = int(os.getenv("BACKTEST_SYMBOLS", "25"))
BACKTEST_DAYS = int(os.getenv("BACKTEST_DAYS", "365"))
BACKTEST_INTERVAL_H = float(os.getenv("BACKTEST_INTERVAL_H", "24"))
PORTFOLIO_VALUE = float(os.getenv("PORTFOLIO_VALUE", "10000"))

engine = BacktestEngine(initial_capital=PORTFOLIO_VALUE)


async def push_log(redis: aioredis.Redis, msg: str, level: str = "info"):
    entry = json.dumps({"ts": round(time.time(), 1), "msg": msg, "level": level})
    await redis.lpush("backtest:log", entry)
    await redis.ltrim("backtest:log", 0, 299)
    await redis.expire("backtest:log", 86400 * 2)


async def run_backtest(redis: aioredis.Redis):
    started = time.time()

    # Clear previous log and write start marker
    await redis.delete("backtest:log")
    await push_log(redis, f"🚀 Backtest başladı — top {BACKTEST_SYMBOLS} sembol, {BACKTEST_DAYS} gün · 1h kline")

    log.info(f"Backtest started — top {BACKTEST_SYMBOLS} symbols, {BACKTEST_DAYS} days of 1h data")

    await redis.set("backtest:status", json.dumps({
        "status": "running",
        "started_at": started,
        "progress": 0.0,
        "completed": 0,
        "total": BACKTEST_SYMBOLS,
    }))

    await push_log(redis, f"📊 Binance Futures en yüksek hacimli {BACKTEST_SYMBOLS} sembol seçiliyor...")
    symbols = fetch_top_symbols(BACKTEST_SYMBOLS)
    preview = ", ".join(symbols[:6]) + ("..." if len(symbols) > 6 else "")
    await push_log(redis, f"✓ {len(symbols)} sembol seçildi: {preview}", "success")

    all_results: list[dict] = []

    for idx, symbol in enumerate(symbols):
        prefix = f"[{idx + 1}/{len(symbols)}]"
        try:
            await push_log(redis, f"{prefix} {symbol} — 1 yıllık kline verisi çekiliyor...")
            log.info(f"[{idx + 1}/{len(symbols)}] {symbol} — fetching klines...")
            klines = fetch_klines(symbol, interval="1h", days=BACKTEST_DAYS)

            if len(klines) < 250:
                await push_log(redis, f"{prefix} {symbol} ⚠ yetersiz veri ({len(klines)} bar), atlandı", "warn")
                log.warning(f"[{symbol}] insufficient data ({len(klines)} bars), skipping")
            else:
                await push_log(redis, f"{prefix} {symbol} — {len(klines)} bar hazır · simülasyon çalışıyor...")
                log.info(f"[{symbol}] running simulation on {len(klines)} bars...")
                result = engine.run(symbol, klines)
                if result and result.get("total_trades", 0) >= 5:
                    all_results.append(result)
                    wr = result["win_rate_pct"]
                    sr = result["sharpe_ratio"]
                    ret = result["total_return_pct"]
                    trades = result["total_trades"]
                    sign = "+" if ret >= 0 else ""
                    lvl = "success" if wr >= 60 and sr >= 1.0 else "info"
                    await push_log(
                        redis,
                        f"{prefix} {symbol} ✓  WR={wr:.1f}%  Sharpe={sr:.2f}  Getiri={sign}{ret:.1f}%  ({trades} işlem)",
                        lvl,
                    )
                    log.info(
                        f"[{symbol}] WR={wr:.1f}%  "
                        f"Sharpe={sr:.2f}  "
                        f"Return={ret:.1f}%  "
                        f"Trades={trades}"
                    )
                else:
                    await push_log(redis, f"{prefix} {symbol} — yetersiz işlem sayısı (<5), atlandı", "warn")
        except Exception as exc:
            await push_log(redis, f"{prefix} {symbol} ✗ hata: {exc}", "error")
            log.error(f"[{symbol}] failed: {exc}", exc_info=True)

        await redis.set("backtest:status", json.dumps({
            "status": "running",
            "started_at": started,
            "progress": round((idx + 1) / len(symbols), 3),
            "completed": idx + 1,
            "total": len(symbols),
            "last_symbol": symbol,
        }))

    if not all_results:
        await push_log(redis, "✗ Kullanılabilir sonuç bulunamadı — backtest iptal edildi", "error")
        log.error("No usable backtest results — aborting")
        await redis.set("backtest:status", json.dumps({"status": "error", "msg": "no results"}))
        return

    # ── Portfolio-level aggregation ────────────────────────────────────────
    total_trades = sum(r["total_trades"] for r in all_results)
    win_rates = [r["win_rate"] for r in all_results if r["total_trades"] >= 10]
    avg_wr = float(np.mean(win_rates)) if win_rates else 0.0

    # Weighted Sharpe (by trade count)
    weighted_sharpe = (
        sum(r["sharpe_ratio"] * r["total_trades"] for r in all_results) / max(total_trades, 1)
    )
    avg_return = float(np.mean([r["total_return_pct"] for r in all_results]))
    avg_dd = float(np.mean([r["max_drawdown_pct"] for r in all_results]))
    avg_pf = float(np.mean([r["profit_factor"] for r in all_results if r["profit_factor"] > 0]))

    # Top/worst symbols
    all_results.sort(key=lambda r: r["sharpe_ratio"], reverse=True)
    top5 = [r["symbol"] for r in all_results[:5]]
    bottom5 = [r["symbol"] for r in all_results[-5:]]

    # Best/worst periods from monthly data
    all_monthly = []
    for r in all_results:
        for m in r.get("monthly_returns", []):
            all_monthly.append(m)

    monthly_by_month: dict[str, list[float]] = {}
    for m in all_monthly:
        k = m["month"]
        monthly_by_month.setdefault(k, []).append(m["return_pct"])

    avg_monthly = {
        k: round(float(np.mean(v)), 2)
        for k, v in sorted(monthly_by_month.items())
    }

    elapsed = round(time.time() - started, 1)
    payload = {
        "summary": {
            "symbols_tested": len(all_results),
            "total_trades": total_trades,
            "avg_win_rate_pct": round(avg_wr * 100, 2),
            "portfolio_sharpe": round(weighted_sharpe, 3),
            "avg_return_pct": round(avg_return, 2),
            "avg_max_drawdown_pct": round(avg_dd, 2),
            "avg_profit_factor": round(avg_pf, 3),
            "top5_symbols": top5,
            "bottom5_symbols": bottom5,
            "days_tested": BACKTEST_DAYS,
            "completed_at": time.time(),
            "elapsed_seconds": elapsed,
            "avg_monthly_returns": avg_monthly,
        },
        "symbols": all_results,
        "config": {
            "atr_sl_mult": engine.atr_sl_mult,
            "atr_tp_mult": engine.atr_tp_mult,
            "rr_ratio": round(engine.atr_tp_mult / engine.atr_sl_mult, 2),
            "max_position_pct": engine.position_pct * 100,
            "confidence_threshold_pct": engine.confidence_threshold * 100,
            "max_hold_bars": engine.max_hold_bars,
            "fee_round_trip_pct": 0.10,
            "interval": "1h",
        },
    }

    await redis.set("backtest:results", json.dumps(payload), ex=86400 * 7)
    await redis.set("backtest:status", json.dumps({
        "status": "complete",
        "completed_at": time.time(),
        "symbols_tested": len(all_results),
        "elapsed_seconds": elapsed,
    }))

    elapsed_min = round(elapsed / 60, 1)
    await push_log(
        redis,
        f"✅ Tamamlandı {elapsed_min}dk'da — {len(all_results)} sembol | "
        f"Ort WR={avg_wr * 100:.1f}%  Sharpe={weighted_sharpe:.2f}  Getiri={avg_return:+.1f}%  "
        f"Toplam {total_trades} işlem",
        "success",
    )

    log.info(
        f"Backtest complete in {elapsed}s — "
        f"{len(all_results)} symbols, "
        f"avg WR={avg_wr * 100:.1f}%, "
        f"portfolio Sharpe={weighted_sharpe:.2f}, "
        f"avg return={avg_return:.1f}%"
    )


async def main():
    redis = await aioredis.from_url(REDIS_URL)

    # Run immediately on startup if no results exist
    results_raw = await redis.get("backtest:results")
    if not results_raw:
        log.info("No cached results — starting backtest immediately on startup")
        await run_backtest(redis)

    while True:
        try:
            # React to trigger set by dashboard POST endpoint
            trigger = await redis.get("backtest:trigger")
            if trigger:
                await redis.delete("backtest:trigger")
                log.info("Trigger received from dashboard — starting backtest")
                await run_backtest(redis)
                await asyncio.sleep(60)
                continue

            status_raw = await redis.get("backtest:status")
            if status_raw:
                status = json.loads(status_raw)
                if status.get("status") == "running":
                    await asyncio.sleep(30)
                    continue

            results_raw = await redis.get("backtest:results")
            if results_raw:
                data = json.loads(results_raw)
                completed_at = data.get("summary", {}).get("completed_at", 0)
                age_h = (time.time() - completed_at) / 3600
                if age_h < BACKTEST_INTERVAL_H:
                    await asyncio.sleep(60)
                    continue

            await run_backtest(redis)

        except Exception as exc:
            log.error(f"Main loop error: {exc}", exc_info=True)
            await asyncio.sleep(60)

        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
