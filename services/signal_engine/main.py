import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from signal_generator import SignalGenerator
from kelly_calculator import KellyCalculator
from signal_validator import SignalValidator
from ensemble import fuse_sources
from learn_adjust import adjust_confidence

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOL_REFRESH_INTERVAL = 300
ACTIVITY_MAX = 500
BATCH_SIZE = 50
SIG_TTL = 120
STATS_KEY = "signal_engine:stats"

generator = SignalGenerator()
kelly = KellyCalculator()
validator = SignalValidator()

# Per-symbol win/loss stats — persisted to Redis for survival across restarts
STATS: dict[str, dict] = {}


def _get_kelly_stats(symbol: str) -> dict:
    s = STATS.get(symbol, {})
    avg_loss = max(float(s.get("avg_loss", 0.01) or 0.01), 1e-6)
    avg_win = max(float(s.get("avg_win", 0.02) or 0.02), 1e-6)
    win_rate = float(s.get("win_rate", 0.55) or 0.55)
    win_rate = min(max(win_rate, 0.05), 0.95)
    return {"win_rate": win_rate, "avg_win": avg_win, "avg_loss": avg_loss}


async def load_stats(redis: aioredis.Redis):
    raw = await redis.get(STATS_KEY)
    if raw:
        STATS.update(json.loads(raw))
        log.info(f"Loaded stats for {len(STATS)} symbols from Redis")


async def save_stats(redis: aioredis.Redis):
    await redis.set(STATS_KEY, json.dumps(STATS), ex=86400 * 14)


async def discover_symbols(redis: aioredis.Redis) -> list[str]:
    keys = await redis.keys("features:latest:*")
    if not keys:
        return []
    return sorted(
        (k.decode() if isinstance(k, bytes) else k).replace("features:latest:", "").upper()
        for k in keys
    )


async def push_activity(redis: aioredis.Redis, event: dict):
    event.setdefault("time", time.time())
    await redis.lpush("activity:feed", json.dumps(event))
    await redis.ltrim("activity:feed", 0, ACTIVITY_MAX - 1)


def _parse_neat(raw: str | None) -> tuple[str | None, float]:
    if not raw:
        return None, 0.0
    try:
        g = json.loads(raw)
        fit = float(g.get("fitness", 0))
        if fit < 0.5:
            return None, 0.0
        direction = "long" if fit >= 1.2 else ("short" if fit < 0.8 else "flat")
        if direction == "flat":
            return None, 0.0
        return direction, min(fit / 3.0, 0.82)
    except Exception:
        return None, 0.0


def _parse_rl(raw: str | None) -> tuple[str | None, float]:
    if not raw:
        return None, 0.0
    try:
        d = json.loads(raw)
        direction = d.get("direction", "flat")
        confidence = float(d.get("confidence", 0))
        if direction == "flat" or confidence <= 0:
            return None, 0.0
        return direction, confidence
    except Exception:
        return None, 0.0


async def publish_universe_snapshot(redis: aioredis.Redis, all_sigs: list[dict], symbols: list[str]):
    """O(1) dashboard read — avoids redis.keys on 500+ symbols."""
    long_c = sum(1 for s in all_sigs if s.get("direction") == "long" and s.get("is_valid"))
    short_c = sum(1 for s in all_sigs if s.get("direction") == "short" and s.get("is_valid"))
    close_c = sum(1 for s in all_sigs if s.get("trade_action") == "close")
    hold_c = sum(1 for s in all_sigs if s.get("trade_action") == "hold")
    pf_raw = await redis.get("portfolio:state:v1")
    pf_open = 0
    if pf_raw:
        try:
            pf_open = int(json.loads(pf_raw).get("total_open", 0))
        except json.JSONDecodeError:
            pass
    payload = {
        "updated_at": time.time(),
        "symbols": sorted(symbols),
        "counts": {
            "total": len(symbols),
            "long": long_c,
            "short": short_c,
            "flat": len(all_sigs) - long_c - short_c,
            "close_actions": close_c,
            "hold_actions": hold_c,
            "open_positions": pf_open,
        },
        "signals": {
            s["symbol"]: {
                "direction": s.get("direction"),
                "confidence": s.get("confidence"),
                "is_valid": s.get("is_valid"),
                "rsi": s.get("rsi"),
                "regime": s.get("regime"),
                "source": s.get("source"),
            }
            for s in all_sigs
        },
    }
    await redis.set("snapshot:universe:v1", json.dumps(payload), ex=180)


async def generate_signal(redis: aioredis.Redis, symbol: str) -> dict | None:
    pipe = redis.pipeline()
    pipe.get(f"context:latest:{symbol}")
    pipe.get(f"agents:verdicts:{symbol}")
    pipe.get(f"agents:verdict:{symbol}")
    pipe.get(f"features:latest:{symbol}")
    pipe.get(f"neat:best_genome:{symbol}")
    pipe.get(f"rl:signal:{symbol}")
    pipe.get(f"oms:position:{symbol}")
    pipe.get(f"learn:profile:{symbol}")
    (
        context_raw,
        agents_raw,
        verdict_raw,
        features_raw,
        neat_raw,
        rl_raw,
        pos_raw,
        learn_raw,
    ) = await pipe.execute()

    context = json.loads(context_raw) if context_raw else {}
    agent_verdicts = json.loads(agents_raw) if agents_raw else []
    verdict = json.loads(verdict_raw) if verdict_raw else {}
    features = json.loads(features_raw) if features_raw else None

    if not features:
        return None

    stats = _get_kelly_stats(symbol)
    kelly_fraction = kelly.calculate(
        stats["win_rate"], stats["avg_win"], stats["avg_loss"], max_fraction=0.05
    )

    signal = generator.generate(symbol, agent_verdicts, kelly_fraction, features)
    if signal is None:
        return None

    neat_dir, neat_conf = _parse_neat(neat_raw)
    rl_dir, rl_conf = _parse_rl(rl_raw)
    final_dir, final_conf, final_source, ensemble_diag = fuse_sources(
        signal.direction,
        signal.confidence,
        neat_dir,
        neat_conf,
        rl_dir,
        rl_conf,
    )
    final_conf, learn_note = adjust_confidence(final_dir, final_conf, learn_raw)
    if learn_note:
        ensemble_diag["learn_adjust"] = learn_note

    signal_dict = {
        "symbol": symbol,
        "direction": final_dir,
        "confidence": final_conf,
        "kelly_fraction": signal.kelly_fraction,
        "source": final_source,
        "agent_source": signal.source,
        "ensemble": ensemble_diag,
        "timestamp": signal.timestamp,
        "crisis_level": context.get("crisis_level", 0),
        "drift_status": context.get("drift_status", features.get("drift_status", "STABLE")),
        "regime": context.get("regime", "unknown"),
        "agent_count": len(agent_verdicts),
        "rsi": round(float(features.get("rsi_14", 50) or 50), 1),
        "macd_hist": round(float(features.get("macd_hist", 0) or 0), 4),
        "volume_ratio": round(float(features.get("volume_ratio", 1) or 1), 2),
    }

    is_valid, reason = validator.validate(signal_dict, context)
    signal_dict["is_valid"] = is_valid
    signal_dict["reject_reason"] = "" if is_valid else reason
    signal_dict["trade_action"] = "none"

    open_pos = json.loads(pos_raw) if pos_raw else None
    if open_pos:
        pos_dir = open_pos.get("direction", "long")
        signal_dict["has_position"] = True
        signal_dict["position_direction"] = pos_dir
        if final_dir == "flat":
            signal_dict["trade_action"] = "close"
            signal_dict["is_valid"] = True
            signal_dict["reject_reason"] = ""
        elif final_dir == pos_dir:
            signal_dict["trade_action"] = "hold"
        elif final_dir in ("long", "short") and final_dir != pos_dir:
            signal_dict["trade_action"] = "reverse"

    if verdict:
        signal_dict["consensus_reasoning"] = verdict.get("consensus_reasoning") or verdict.get("reasoning", "")
        signal_dict["dissent_risk"] = verdict.get("dissent_risk", "")
        signal_dict["probabilities"] = verdict.get("probabilities")
        signal_dict["targets"] = verdict.get("targets")
        signal_dict["trade_lessons"] = verdict.get("trade_lessons", [])

    sym_stats = STATS.get(symbol, {})
    if sym_stats.get("wins", 0) + sym_stats.get("losses", 0) >= 5:
        signal_dict["live_win_rate"] = round(sym_stats.get("win_rate", 0) * 100, 1)

    return signal_dict


async def stats_listener(redis: aioredis.Redis):
    """Update per-symbol stats from closed trade events (published by shadow/OMS)."""
    pubsub = redis.pubsub()
    await pubsub.subscribe("ch:trade_closed")
    log.info("Subscribed to ch:trade_closed for stats updates")
    save_interval = 0
    async for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        try:
            trade = json.loads(msg["data"])
            symbol = trade.get("symbol")
            if not symbol:
                continue
            pnl_pct = float(trade.get("pnl_pct", 0))
            win = pnl_pct > 0
            s = STATS.setdefault(symbol, {
                "wins": 0, "losses": 0, "total_win": 0.0, "total_loss": 0.0,
                "win_rate": 0.55, "avg_win": 0.02, "avg_loss": 0.01,
            })
            if win:
                s["wins"] += 1
                s["total_win"] += pnl_pct
            else:
                s["losses"] += 1
                s["total_loss"] += abs(pnl_pct)
            total = s["wins"] + s["losses"]
            s["win_rate"] = s["wins"] / total if total > 0 else 0.55
            s["avg_win"] = s["total_win"] / max(s["wins"], 1)
            s["avg_loss"] = max(s["total_loss"] / max(s["losses"], 1), 1e-6)

            save_interval += 1
            if save_interval % 10 == 0:
                await save_stats(redis)
        except Exception as e:
            log.error(f"Stats listener error: {e}")


async def main():
    log.info("signal_engine starting — dynamic symbol discovery")
    redis = await aioredis.from_url(REDIS_URL)
    redis_sub = await aioredis.from_url(REDIS_URL)

    await load_stats(redis)

    active_symbols: list[str] = []
    for attempt in range(12):
        active_symbols = await discover_symbols(redis)
        if active_symbols:
            break
        log.info(f"Waiting for features in Redis (attempt {attempt + 1}/12)...")
        await asyncio.sleep(10)

    if not active_symbols:
        log.warning("No symbols found — using fallback")
        active_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

    log.info(f"signal_engine ready — {len(active_symbols)} symbols")

    async def signal_loop():
        active_set: set[str] = set(active_symbols)
        last_refresh = time.time()
        cycle = 0

        while True:
            if time.time() - last_refresh > SYMBOL_REFRESH_INTERVAL:
                new_symbols = await discover_symbols(redis)
                if new_symbols:
                    active_set = set(new_symbols)
                last_refresh = time.time()

            all_sigs: list[dict] = []

            async def _gen(symbol: str):
                try:
                    sig = await generate_signal(redis, symbol)
                    if sig is not None:
                        await redis.set(f"signal:latest:{symbol}", json.dumps(sig), ex=SIG_TTL)
                        await redis.publish(f"ch:signal:{symbol}", symbol)
                        all_sigs.append(sig)
                except Exception as e:
                    log.exception(f"Signal error for {symbol}: {e}")

            symbols_list = list(active_set)
            for i in range(0, len(symbols_list), BATCH_SIZE):
                await asyncio.gather(*[_gen(s) for s in symbols_list[i:i + BATCH_SIZE]])

            signal_count = 0
            for sig in all_sigs:
                if sig["direction"] != "flat" and sig.get("is_valid"):
                    signal_count += 1
                    log.info(f"[{sig['symbol']}] {sig['direction'].upper()} conf={sig['confidence']:.2f}")
                    await push_activity(redis, {
                        "type": "signal",
                        "symbol": sig["symbol"],
                        "direction": sig["direction"],
                        "confidence": sig["confidence"],
                        "source": sig["source"],
                        "rsi": sig.get("rsi"),
                        "regime": sig.get("regime"),
                    })

            await publish_universe_snapshot(redis, all_sigs, list(active_set))
            await redis.set("system:heartbeat:signal_engine", str(time.time()), ex=120)

            cycle += 1
            if cycle % 12 == 0:
                long_c = sum(1 for s in all_sigs if s["direction"] == "long" and s.get("is_valid"))
                short_c = sum(1 for s in all_sigs if s["direction"] == "short" and s.get("is_valid"))
                log.info(f"Cycle {cycle}: {len(active_set)} symbols, {signal_count} active signals")
                await push_activity(redis, {
                    "type": "scan_summary",
                    "total": len(active_set),
                    "long": long_c,
                    "short": short_c,
                    "flat": len(all_sigs) - long_c - short_c,
                })
                extremes = sorted(
                    [s for s in all_sigs if s.get("rsi") is not None and (s["rsi"] < 32 or s["rsi"] > 68)],
                    key=lambda s: abs(s["rsi"] - 50),
                    reverse=True,
                )[:5]
                for s in extremes:
                    await push_activity(redis, {
                        "type": "rsi_alert",
                        "symbol": s["symbol"],
                        "direction": s["direction"],
                        "confidence": s["confidence"],
                        "source": "rsi_scan",
                        "rsi": s["rsi"],
                        "label": "Aşırı Satış" if s["rsi"] < 32 else "Aşırı Alış",
                    })

            await asyncio.sleep(5)

    await asyncio.gather(signal_loop(), stats_listener(redis_sub))


if __name__ == "__main__":
    asyncio.run(main())
