"""
Continuous full-universe backtest — processes TOP_N symbols in chunks 24/7.
Persists per-symbol results + AI lessons; merges rolling portfolio summary.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import numpy as np
import redis.asyncio as aioredis

from historical_fetcher import fetch_klines, fetch_top_symbols
from backtest_engine import BacktestEngine
from insights import build_symbol_insights, insight_to_lesson_line

log = logging.getLogger(__name__)

BACKTEST_TOTAL = int(os.getenv("BACKTEST_TOTAL_SYMBOLS", "500"))
BACKTEST_CHUNK = int(os.getenv("BACKTEST_CHUNK_SIZE", "20"))
BACKTEST_DAYS = int(os.getenv("BACKTEST_DAYS", "365"))
BACKTEST_DAYS_2 = int(os.getenv("BACKTEST_DAYS_EXTENDED", "0"))  # optional 2nd pass years
CHUNK_PAUSE_SEC = float(os.getenv("BACKTEST_CHUNK_PAUSE_SEC", "3"))
STATE_KEY = "backtest:queue:state"
INDEX_KEY = "backtest:symbols:index"


async def discover_universe(redis: aioredis.Redis) -> list[str]:
    for key in ("ingestion:symbols", "snapshot:universe:v1"):
        raw = await redis.get(key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return sorted(data)[:BACKTEST_TOTAL]
            syms = data.get("symbols") if isinstance(data, dict) else None
            if isinstance(syms, list) and syms:
                return sorted(syms)[:BACKTEST_TOTAL]
        except json.JSONDecodeError:
            continue
    return fetch_top_symbols(BACKTEST_TOTAL)


async def push_log(redis: aioredis.Redis, msg: str, level: str = "info"):
    entry = json.dumps({"ts": round(time.time(), 1), "msg": msg, "level": level})
    await redis.lpush("backtest:log", entry)
    await redis.ltrim("backtest:log", 0, 499)
    await redis.expire("backtest:log", 86400 * 14)


async def load_state(redis: aioredis.Redis, universe: list[str]) -> dict:
    raw = await redis.get(STATE_KEY)
    if raw:
        try:
            st = json.loads(raw)
            if st.get("universe"):
                return st
        except json.JSONDecodeError:
            pass
    return {
        "universe": universe,
        "cursor": 0,
        "pass_number": 1,
        "symbols_completed_pass": 0,
        "total_symbols": len(universe),
    }


async def save_state(redis: aioredis.Redis, state: dict) -> None:
    await redis.set(STATE_KEY, json.dumps(state), ex=86400 * 30)


async def persist_symbol_result(
    redis: aioredis.Redis, engine: BacktestEngine, symbol: str, klines: list
) -> dict | None:
    if len(klines) < 250:
        return None
    result = engine.run(symbol, klines)
    if not result or result.get("total_trades", 0) < 5:
        return None

    await redis.set(f"backtest:symbol:{symbol}", json.dumps(result), ex=86400 * 30)
    await redis.sadd(INDEX_KEY, symbol)

    insights = build_symbol_insights(result)
    if insights:
        await redis.set(f"backtest:insights:{symbol}", json.dumps(insights), ex=86400 * 30)
        lesson_line = insight_to_lesson_line(insights)
        if lesson_line:
            lesson_payload = json.dumps({
                "source": "backtest",
                "symbol": symbol,
                "pnl_pct": result.get("total_return_pct", 0) / 100,
                "was_winner": result.get("total_return_pct", 0) > 0,
                "error_category": "backtest_regime_lesson",
                "text": lesson_line,
                "insights": insights,
            })
            await redis.lpush(f"trade:lessons:{symbol}", lesson_payload)
            await redis.ltrim(f"trade:lessons:{symbol}", 0, 19)

    return result


async def merge_aggregate(redis: aioredis.Redis, engine: BacktestEngine, days: int) -> None:
    symbols = await redis.smembers(INDEX_KEY)
    if not symbols:
        return
    all_results: list[dict] = []
    for sym in symbols:
        s = sym.decode() if isinstance(sym, bytes) else sym
        raw = await redis.get(f"backtest:symbol:{s}")
        if raw:
            try:
                all_results.append(json.loads(raw))
            except json.JSONDecodeError:
                pass

    if not all_results:
        return

    total_trades = sum(r["total_trades"] for r in all_results)
    win_rates = [r["win_rate"] for r in all_results if r["total_trades"] >= 10]
    avg_wr = float(np.mean(win_rates)) if win_rates else 0.0
    weighted_sharpe = sum(r["sharpe_ratio"] * r["total_trades"] for r in all_results) / max(total_trades, 1)
    avg_return = float(np.mean([r["total_return_pct"] for r in all_results]))
    avg_dd = float(np.mean([r["max_drawdown_pct"] for r in all_results]))
    avg_pf = float(np.mean([r["profit_factor"] for r in all_results if r["profit_factor"] > 0]))

    all_results.sort(key=lambda r: r["sharpe_ratio"], reverse=True)

    monthly_acc: dict[str, list[float]] = {}
    for r in all_results:
        for m in r.get("monthly_returns") or []:
            month = m.get("month")
            if not month:
                continue
            monthly_acc.setdefault(month, []).append(float(m.get("return_pct", 0)))
    avg_monthly = {
        m: round(sum(v) / len(v), 2) for m, v in sorted(monthly_acc.items()) if v
    }

    payload = {
        "summary": {
            "symbols_tested": len(all_results),
            "universe_target": BACKTEST_TOTAL,
            "total_trades": total_trades,
            "avg_win_rate_pct": round(avg_wr * 100, 2),
            "portfolio_sharpe": round(weighted_sharpe, 3),
            "avg_return_pct": round(avg_return, 2),
            "avg_max_drawdown_pct": round(avg_dd, 2),
            "avg_profit_factor": round(avg_pf, 3),
            "top5_symbols": [r["symbol"] for r in all_results[:5]],
            "bottom5_symbols": [r["symbol"] for r in all_results[-5:]],
            "days_tested": days,
            "completed_at": time.time(),
            "elapsed_seconds": 0,
            "avg_monthly_returns": avg_monthly,
            "mode": "continuous_chunk",
        },
        "symbols": all_results,
        "config": {
            "chunk_size": BACKTEST_CHUNK,
            "total_symbols": BACKTEST_TOTAL,
            "interval": "1h",
        },
    }
    await redis.set("backtest:results", json.dumps(payload), ex=86400 * 14)


async def run_one_chunk(redis: aioredis.Redis, engine: BacktestEngine) -> None:
    universe = await discover_universe(redis)
    if not universe:
        universe = fetch_top_symbols(BACKTEST_TOTAL)

    state = await load_state(redis, universe)
    state["universe"] = universe
    state["total_symbols"] = len(universe)
    cursor = int(state.get("cursor", 0))
    chunk = universe[cursor : cursor + BACKTEST_CHUNK]
    if not chunk:
        state["cursor"] = 0
        state["pass_number"] = int(state.get("pass_number", 1)) + 1
        state["symbols_completed_pass"] = 0
        await save_state(redis, state)
        await push_log(redis, f"🔄 Tur {state['pass_number']} tamamlandı — yeni tur başlıyor", "success")
        return

    pass_n = state.get("pass_number", 1)
    chunks_total = (len(universe) + BACKTEST_CHUNK - 1) // BACKTEST_CHUNK
    chunk_idx = cursor // BACKTEST_CHUNK + 1

    await redis.set("backtest:status", json.dumps({
        "status": "running",
        "mode": "continuous",
        "pass_number": pass_n,
        "chunk_index": chunk_idx,
        "chunks_total": chunks_total,
        "symbols_total": len(universe),
        "cursor": cursor,
        "chunk_size": len(chunk),
        "started_at": time.time(),
    }))

    days = BACKTEST_DAYS_2 if pass_n > 1 and BACKTEST_DAYS_2 > 0 else BACKTEST_DAYS
    await push_log(
        redis,
        f"📦 Parça {chunk_idx}/{chunks_total} (Tur {pass_n}) — {len(chunk)} coin · {days} gün veri",
    )

    for i, symbol in enumerate(chunk):
        try:
            klines = fetch_klines(symbol, interval="1h", days=days)
            result = await persist_symbol_result(redis, engine, symbol, klines)
            if result:
                await push_log(
                    redis,
                    f"  ✓ {symbol} WR={result['win_rate_pct']:.0f}% Sharpe={result['sharpe_ratio']:.2f}",
                    "success" if result["win_rate_pct"] >= 55 else "info",
                )
        except Exception as exc:
            await push_log(redis, f"  ✗ {symbol}: {exc}", "error")

        progress = (cursor + i + 1) / len(universe)
        await redis.set("backtest:status", json.dumps({
            "status": "running",
            "mode": "continuous",
            "pass_number": pass_n,
            "chunk_index": chunk_idx,
            "chunks_total": chunks_total,
            "symbols_total": len(universe),
            "completed": cursor + i + 1,
            "progress": round(progress, 4),
            "last_symbol": symbol,
        }))

    state["cursor"] = cursor + len(chunk)
    state["symbols_completed_pass"] = int(state.get("symbols_completed_pass", 0)) + len(chunk)
    await save_state(redis, state)

    await merge_aggregate(redis, engine, days)
    await push_log(redis, f"📊 Özet güncellendi — {await redis.scard(INDEX_KEY)} coin arşivde", "success")

    if state["cursor"] >= len(universe):
        state["cursor"] = 0
        state["pass_number"] = pass_n + 1
        state["symbols_completed_pass"] = 0
        await save_state(redis, state)

    await asyncio.sleep(CHUNK_PAUSE_SEC)


async def continuous_loop(redis: aioredis.Redis, engine: BacktestEngine) -> None:
    log.info(
        f"Continuous backtest — {BACKTEST_TOTAL} symbols, chunk={BACKTEST_CHUNK}, days={BACKTEST_DAYS}"
    )
    await push_log(redis, f"⚡ Sürekli backtest modu — evren: {BACKTEST_TOTAL} coin, parça: {BACKTEST_CHUNK}")

    while True:
        try:
            trigger = await redis.get("backtest:trigger")
            if trigger:
                await redis.delete("backtest:trigger")
                await push_log(redis, "▶ Manuel tetik — sonraki parça hızlandırıldı")

            status_raw = await redis.get("backtest:status")
            if status_raw:
                st = json.loads(status_raw)
                if st.get("status") == "paused":
                    await asyncio.sleep(30)
                    continue

            await run_one_chunk(redis, engine)
        except Exception as exc:
            log.error(f"Chunk loop error: {exc}", exc_info=True)
            await push_log(redis, f"Loop hata: {exc}", "error")
            await asyncio.sleep(60)
