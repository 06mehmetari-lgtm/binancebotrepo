import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from signal_generator import SignalGenerator
from kelly_calculator import KellyCalculator
from signal_validator import SignalValidator
from atr_stoploss import ATRStopLoss
from portfolio_guard import PortfolioGuard
from consensus_tracker import consensus_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOL_REFRESH_INTERVAL = 300
ACTIVITY_MAX = 500
BATCH_SIZE = 50
SIG_TTL = 120
STATS_KEY = "signal_engine:stats"

generator      = SignalGenerator()
kelly          = KellyCalculator()
validator      = SignalValidator()
atr_calculator = ATRStopLoss()
port_guard     = PortfolioGuard()

# Per-symbol win/loss stats — persisted to Redis for survival across restarts
STATS: dict[str, dict] = {}


def _get_kelly_stats(symbol: str) -> dict:
    s = STATS.get(symbol, {})
    return {
        "win_rate": s.get("win_rate", 0.55),
        "avg_win": s.get("avg_win", 0.02),
        "avg_loss": s.get("avg_loss", 0.01),
    }


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


async def _get_open_positions(redis: aioredis.Redis) -> list[dict]:
    """Fetch all open positions from Redis for portfolio guard."""
    keys = await redis.keys("oms:position:*")
    if not keys:
        return []
    pipe = redis.pipeline()
    for k in keys:
        pipe.get(k)
    raws = await pipe.execute()
    positions = []
    for raw in raws:
        if raw:
            try:
                positions.append(json.loads(raw))
            except Exception:
                pass
    return positions


async def generate_signal(redis: aioredis.Redis, symbol: str) -> dict | None:
    context_raw     = await redis.get(f"context:latest:{symbol}")
    agents_raw      = await redis.get(f"agents:verdicts:{symbol}")
    features_raw    = await redis.get(f"features:latest:{symbol}")
    coin_stats_raw  = await redis.hgetall(f"coin:stats:{symbol}")

    context        = json.loads(context_raw)  if context_raw  else {}
    agent_verdicts = json.loads(agents_raw)   if agents_raw   else []
    features       = json.loads(features_raw) if features_raw else None

    if not features:
        return None

    # Per-coin history — used for confidence adjustment (Step 4) and blocking (Step 7)
    coin_trades = int(coin_stats_raw.get(b"total_trades", 0) or 0)
    coin_wr     = float(coin_stats_raw.get(b"win_rate", 0.5) or 0.5)
    coin_consec = int(coin_stats_raw.get(b"consecutive_losses", 0) or 0)

    stats = _get_kelly_stats(symbol)
    kelly_fraction = kelly.calculate(
        stats["win_rate"], stats["avg_win"], stats["avg_loss"], max_fraction=0.05
    )

    # ── ATR-based stop-loss / take-profit ──────────────────────────────────
    atr_pct = float(features.get("atr_pct", 1.0) or 1.0)
    regime  = context.get("regime", "unknown")
    stop_mult, tp_mult = atr_calculator.regime_multipliers(regime)

    # ── ML score from feature engine ───────────────────────────────────────
    ml_score = float(features.get("ml_score", 0.0) or 0.0)

    # ── ML fallback when no LLM verdicts available (Step 9) ───────────────
    # Requires |ml_score| > 0.65 to pass MIN_CONFIDENCE=0.70 validator
    if not agent_verdicts and abs(ml_score) > 0.65:
        fallback_dir  = "long" if ml_score > 0 else "short"
        fallback_conf = round(min(0.80, 0.45 + abs(ml_score) * 0.45), 3)
        agent_verdicts = [{
            "agent": "ml_fallback", "direction": fallback_dir,
            "signal": fallback_dir, "confidence": fallback_conf,
        }]
        log.debug(f"[{symbol}] ML fallback: {fallback_dir} conf={fallback_conf:.2f} ml={ml_score:.3f}")

    # ── RL (PPO) signal ────────────────────────────────────────────────────
    rl_raw  = await redis.get(f"rl:signal:{symbol}")
    rl_data = json.loads(rl_raw) if rl_raw else {}
    rl_dir  = rl_data.get("direction", "flat")
    rl_conf = float(rl_data.get("confidence", 0.0))
    if rl_dir != "flat" and rl_conf > 0:
        agent_verdicts = list(agent_verdicts) + [{
            "agent": "rl_ppo", "direction": rl_dir,
            "signal": rl_dir, "confidence": rl_conf,
        }]

    # ── NEAT evolution signal ──────────────────────────────────────────────
    neat_raw  = await redis.get(f"neat:signal:{symbol}")
    neat_data = json.loads(neat_raw) if neat_raw else {}
    neat_dir  = neat_data.get("direction", "flat")
    neat_conf = float(neat_data.get("confidence", 0.0))
    neat_fit  = float(neat_data.get("fitness", 0.0))
    # Only use NEAT signal if its genome has meaningful fitness
    if neat_dir != "flat" and neat_conf > 0 and neat_fit > 0.05:
        agent_verdicts = list(agent_verdicts) + [{
            "agent": "neat_evolution", "direction": neat_dir,
            "signal": neat_dir, "confidence": neat_conf,
        }]

    # Single-pass generation: use a neutral direction for ATR calc, then generate once with stops
    # Determine direction from votes before full generation to compute ATR levels
    if agent_verdicts:
        votes: dict[str, float] = {"long": 0.0, "short": 0.0, "flat": 0.0}
        for v in agent_verdicts:
            d = v.get("direction", v.get("signal", "flat"))
            c = float(v.get("confidence", 0.5))
            if d in votes:
                votes[d] += c
        prelim_dir = max(votes, key=votes.__getitem__)
    else:
        prelim_dir = "flat"

    stops = atr_calculator.calculate(prelim_dir, atr_pct, stop_mult, tp_mult)

    # Single generate call with stops already computed
    signal = generator.generate(
        symbol, agent_verdicts, kelly_fraction, features,
        ml_score=ml_score,
        stop_pct=stops["stop_pct"],
        tp_pct=stops["tp_pct"],
        risk_reward=stops["risk_reward"],
    )
    if signal is None:
        return None

    # ── Portfolio guard ────────────────────────────────────────────────────
    if signal.direction != "flat":
        open_positions = await _get_open_positions(redis)
        allowed, pg_reason, conf_mod = port_guard.check(
            symbol, signal.direction, open_positions, features
        )
        if not allowed:
            # Convert to flat with reject reason
            signal_dict = {
                "symbol": symbol,
                "direction": "flat",
                "confidence": signal.confidence,
                "kelly_fraction": kelly_fraction,
                "source": signal.source,
                "timestamp": signal.timestamp,
                "crisis_level": context.get("crisis_level", 0),
                "drift_status": context.get("drift_status", features.get("drift_status", "STABLE")),
                "regime": regime,
                "agent_count": len(agent_verdicts),
                "rsi": round(float(features.get("rsi_14", 50) or 50), 1),
                "macd_hist": round(float(features.get("macd_hist", 0) or 0), 4),
                "volume_ratio": round(float(features.get("volume_ratio", 1) or 1), 2),
                "ml_score": ml_score,
                "stop_pct": 0.0, "tp_pct": 0.0, "risk_reward": 0.0,
                "is_valid": False,
                "reject_reason": f"portfolio_guard: {pg_reason}",
            }
            return signal_dict
        # Apply confidence penalty for correlated positions
        adjusted_conf = max(0.0, signal.confidence + conf_mod)
        if adjusted_conf < signal.confidence:
            from dataclasses import replace
            signal = replace(signal, confidence=round(adjusted_conf, 4))

    signal_dict = {
        "symbol": symbol,
        "direction": signal.direction,
        "confidence": signal.confidence,
        "kelly_fraction": signal.kelly_fraction,
        "source": signal.source,
        "timestamp": signal.timestamp,
        "crisis_level": context.get("crisis_level", 0),
        "drift_status": context.get("drift_status", features.get("drift_status", "STABLE")),
        "regime": regime,
        "agent_count": len(agent_verdicts),
        "rsi": round(float(features.get("rsi_14", 50) or 50), 1),
        "macd_hist": round(float(features.get("macd_hist", 0) or 0), 4),
        "volume_ratio": round(float(features.get("volume_ratio", 1) or 1), 2),
        "ml_score": ml_score,
        "rl_direction": rl_dir,
        "neat_direction": neat_dir,
        "stop_pct": signal.stop_pct,
        "tp_pct": signal.tp_pct,
        "risk_reward": signal.risk_reward,
    }

    # Inject coin stats into signal for validator and downstream consumers
    signal_dict["consecutive_losses"] = coin_consec

    # Coin history confidence adjustment (Step 4) — only after ≥10 trades
    if coin_trades >= 10:
        if coin_wr < 0.35:
            signal_dict["confidence"] = round(max(0.0, signal_dict["confidence"] - 0.10), 4)
        elif coin_wr < 0.45:
            signal_dict["confidence"] = round(max(0.0, signal_dict["confidence"] - 0.05), 4)
        elif coin_wr > 0.65:
            signal_dict["confidence"] = round(min(1.0, signal_dict["confidence"] + 0.05), 4)

    is_valid, reason = validator.validate(signal_dict, context)
    signal_dict["is_valid"] = is_valid
    signal_dict["reject_reason"] = "" if is_valid else reason

    # Shadow-tier validity: lower threshold for learning (Step 8)
    shadow_conf = signal_dict["confidence"]
    signal_dict["shadow_valid"] = (
        shadow_conf >= 0.55
        and signal_dict["direction"] != "flat"
        and coin_consec < 3
    )

    # Snapshot entry features for ML labeling.
    # feature_engine overwrites ml:signal_features:{symbol} every second —
    # we copy it here at signal time so feedback_writer can retrieve the
    # correct feature vector when the trade closes (hours later).
    if signal_dict["direction"] != "flat" and is_valid:
        entry_vec = await redis.get(f"ml:signal_features:{symbol}")
        if entry_vec:
            await redis.set(f"ml:entry_features:{symbol}", entry_vec, ex=14400)  # 4h TTL

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
            s["avg_loss"] = s["total_loss"] / max(s["losses"], 1)

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
                    log.error(f"Signal error for {symbol}: {e}")

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

    redis_consensus = await aioredis.from_url(REDIS_URL)
    await asyncio.gather(
        signal_loop(),
        stats_listener(redis_sub),
        consensus_loop(redis_consensus),
    )


if __name__ == "__main__":
    asyncio.run(main())
