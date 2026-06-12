"""
Learning Engine — continual market behavior learning (sub-second tick ingestion).

Subscribes to feature/context updates, tracks price reactions per regime and driver,
writes learn:profile:* and trade:lessons for the 9-agent debate system.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from behavior_tracker import SymbolLearner, TickSample
from lesson_writer import persist_global, persist_profile
from llm_synthesizer import synthesize_coin_insight

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
GLOBAL_SYNC_SEC = int(os.getenv("LEARNING_GLOBAL_SYNC_SEC", "30"))
PROFILE_WRITE_EVERY = int(os.getenv("LEARNING_PROFILE_EVERY_N", "30"))
LLM_EVERY_N = int(os.getenv("LEARNING_LLM_EVERY_N", "90"))


class LearningEngine:
    def __init__(self):
        self._learners: dict[str, SymbolLearner] = {}

    def _learner(self, symbol: str) -> SymbolLearner:
        if symbol not in self._learners:
            self._learners[symbol] = SymbolLearner(symbol=symbol)
        return self._learners[symbol]

    async def ingest_symbol(self, redis: aioredis.Redis, symbol: str) -> bool:
        pipe = redis.pipeline()
        pipe.get(f"features:latest:{symbol}")
        pipe.get(f"context:latest:{symbol}")
        pipe.get(f"binance:ticker:{symbol.lower()}")
        feat_raw, ctx_raw, ticker_raw = await pipe.execute()

        if not feat_raw:
            return False

        try:
            features = json.loads(feat_raw)
            context = json.loads(ctx_raw) if ctx_raw else {}
        except json.JSONDecodeError:
            return False

        price = float(features.get("close") or features.get("last_price") or 0)
        if ticker_raw and price <= 0:
            try:
                td = json.loads(ticker_raw)
                d = td.get("data", td)
                bid = float(d.get("b", 0) or 0)
                ask = float(d.get("a", bid) or bid)
                price = (bid + ask) / 2 if bid else 0
            except json.JSONDecodeError:
                pass
        if price <= 0:
            return False

        sample = TickSample(
            ts=time.time(),
            price=price,
            regime=str(context.get("regime", "unknown")),
            rsi=float(features.get("rsi_14", 50) or 50),
            macd_hist=float(features.get("macd_hist", 0) or 0),
            imbalance_5=float(features.get("imbalance_5", 0) or 0),
            funding=float(features.get("funding_rate", 0) or context.get("funding_rate", 0) or 0),
            drift=str(context.get("drift_status", features.get("drift_status", "STABLE"))),
            crisis=int(context.get("crisis_level", 0) or 0),
            volume_ratio=float(features.get("volume_ratio", 1) or 1),
        )

        learner = self._learner(symbol)
        new_lessons = learner.observe(sample)

        if learner.updates % PROFILE_WRITE_EVERY == 0:
            profile = learner.build_profile()

            stage = profile.get("learning_stage", "L0")
            hot_syms = await _open_position_symbols(redis)
            llm_every = max(15, LLM_EVERY_N // 3) if symbol in hot_syms else LLM_EVERY_N
            if stage in ("L1", "L2", "L3") and learner.updates % llm_every == 0:
                llm = await asyncio.get_event_loop().run_in_executor(
                    None, synthesize_coin_insight, symbol, profile
                )
                if llm:
                    profile["ai_insight"] = llm.get("ai_insight", "")
                    if llm.get("best_entry_hint"):
                        profile["best_entry_hint"] = llm["best_entry_hint"]
                    if llm.get("avoid_hint"):
                        profile["avoid_hint"] = llm["avoid_hint"]
                    profile["llm_provider"] = llm.get("llm_provider")
                    learner.llm_enrich_count += 1

            await persist_profile(redis, profile, new_lessons)
            if learner.updates % (PROFILE_WRITE_EVERY * 20) == 0:
                log.info(
                    f"[learn] {symbol} {stage} depth={profile.get('depth_score')} "
                    f"drivers={len(profile['drivers'])} llm={bool(profile.get('ai_insight'))}"
                )
        return True

    async def on_trade_closed(self, redis: aioredis.Redis, trade: dict):
        symbol = str(trade.get("symbol", "")).upper()
        if not symbol:
            return
        pnl = float(trade.get("pnl_pct", 0) or 0)
        direction = trade.get("direction", "long")
        won = pnl > 0
        learner = self._learner(symbol)

        imbalance_5 = None
        funding = None
        feat_raw = await redis.get(f"features:latest:{symbol}")
        if feat_raw:
            try:
                features = json.loads(feat_raw)
                imbalance_5 = float(features.get("imbalance_5", 0) or 0)
                funding = float(features.get("funding_rate", 0) or 0)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        lessons = learner.record_trade_close(
            direction,
            pnl,
            won,
            imbalance_5=imbalance_5,
            funding=funding,
            source=str(trade.get("source", trade.get("shadow_id", ""))),
            exit_reason=str(trade.get("exit_reason", "")),
            peak_upnl_pct=trade.get("peak_upnl_pct"),
            hold_seconds=float(trade.get("hold_seconds", 0) or 0),
        )
        await persist_profile(redis, learner.build_profile(), lessons)
        log.info(f"[learn] trade_closed {symbol} {direction} pnl={pnl:+.2%} lessons={len(lessons)}")


async def pubsub_listener(engine: LearningEngine, redis_cmd: aioredis.Redis):
    """Dedicated pubsub connection — features + trade_closed on one listener."""
    redis_sub = await aioredis.from_url(REDIS_URL)
    pubsub = redis_sub.pubsub()
    await pubsub.psubscribe("ch:features:*")
    await pubsub.subscribe("ch:trade_closed")
    log.info("learning_engine: pubsub (features + trade_closed)")
    sem = asyncio.Semaphore(int(os.getenv("LEARNING_CONCURRENCY", "80")))

    async def _ingest(sym: str):
        async with sem:
            await engine.ingest_symbol(redis_cmd, sym)

    try:
        async for msg in pubsub.listen():
            try:
                mtype = msg.get("type")
                if mtype == "pmessage":
                    sym = msg.get("data")
                    if isinstance(sym, bytes):
                        sym = sym.decode()
                    if not sym or not str(sym).endswith("USDT"):
                        ch = msg.get("channel", b"")
                        if isinstance(ch, bytes):
                            ch = ch.decode()
                        sym = ch.split(":")[-1] if ":" in ch else sym
                    await _ingest(str(sym).upper())
                elif mtype == "message":
                    trade = json.loads(msg["data"])
                    await engine.on_trade_closed(redis_cmd, trade)
            except Exception as e:
                log.debug(f"pubsub: {e}")
    finally:
        try:
            await pubsub.aclose()
        except Exception:
            pass
        try:
            await redis_sub.aclose()
        except Exception:
            pass


async def _open_position_symbols(redis: aioredis.Redis) -> list[str]:
    raw = await redis.get("portfolio:state:v1")
    if not raw:
        return []
    try:
        state = json.loads(raw)
        return list(
            dict.fromkeys(
                p["symbol"]
                for p in state.get("positions", [])
                if p.get("symbol", "").endswith("USDT")
            )
        )
    except json.JSONDecodeError:
        return []


async def open_position_boost_loop(engine: LearningEngine, redis: aioredis.Redis):
    """Açık pozisyon coinleri — evrenden bağımsız, saniyede birkaç kez öğrenme."""
    interval = float(os.getenv("LEARNING_OPEN_POSITION_SEC", "0.5"))
    while True:
        try:
            hot = await _open_position_symbols(redis)
            if hot:
                await asyncio.gather(
                    *[engine.ingest_symbol(redis, s) for s in hot],
                    return_exceptions=True,
                )
        except Exception as e:
            log.debug(f"open_position_boost: {e}")
        await asyncio.sleep(interval)


async def scan_loop(engine: LearningEngine, redis: aioredis.Redis):
    """Fallback: scan universe every 2s so learning never stalls if pub/sub drops."""
    while True:
        try:
            hot = await _open_position_symbols(redis)
            raw = await redis.get("ingestion:symbols")
            symbols: list[str] = []
            if raw:
                data = json.loads(raw)
                symbols = data.get("symbols", []) if isinstance(data, dict) else []
            if not symbols:
                snap = await redis.get("snapshot:universe:v1")
                if snap:
                    symbols = json.loads(snap).get("symbols", [])
            if not symbols:
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(cursor, match="features:latest:*", count=200)
                    for k in keys:
                        key = k.decode() if isinstance(k, bytes) else k
                        symbols.append(key.replace("features:latest:", ""))
                    if cursor == 0:
                        break

            # Açık pozisyonlar her turda önce (öncelikli öğrenme)
            ordered = list(dict.fromkeys(hot + [s for s in symbols if s not in hot]))
            batch = int(os.getenv("LEARNING_SCAN_BATCH", "100"))
            for i in range(0, min(len(ordered), 500), batch):
                await asyncio.gather(
                    *[engine.ingest_symbol(redis, s) for s in ordered[i : i + batch]],
                    return_exceptions=True,
                )
            await persist_global(redis, engine._learners)
        except Exception as e:
            log.error(f"scan_loop: {e}")
        await asyncio.sleep(float(os.getenv("LEARNING_SCAN_SEC", "2")))


async def global_sync_loop(engine: LearningEngine, redis: aioredis.Redis):
    while True:
        try:
            await persist_global(redis, engine._learners)
        except Exception as e:
            log.error(f"global_sync: {e}")
        await asyncio.sleep(GLOBAL_SYNC_SEC)


async def main():
    try:
        from llm_providers import any_cloud_llm_configured
        groq = any_cloud_llm_configured()
    except ImportError:
        groq = bool(os.getenv("GROQ_API_KEY", ""))
    ollama = os.getenv("OLLAMA_URL", "")
    log.info(
        f"learning_engine starting — Groq={'on' if groq else 'off'} "
        f"Ollama={'on' if ollama else 'off'}"
    )
    redis = await aioredis.from_url(REDIS_URL)
    engine = LearningEngine()
    await asyncio.gather(
        pubsub_listener(engine, redis),
        open_position_boost_loop(engine, redis),
        scan_loop(engine, redis),
        global_sync_loop(engine, redis),
    )


if __name__ == "__main__":
    asyncio.run(main())
