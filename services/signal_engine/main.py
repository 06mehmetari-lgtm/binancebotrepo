import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from signal_generator import SignalGenerator
from kelly_calculator import KellyCalculator
from signal_validator import SignalValidator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOL_REFRESH_INTERVAL = 300
ACTIVITY_MAX = 500
BATCH_SIZE = 50  # concurrent symbols per gather call
SIG_TTL = 120   # seconds

generator = SignalGenerator()
kelly = KellyCalculator()
validator = SignalValidator()

# Running per-symbol stats updated from autopsy results
STATS: dict[str, dict] = {}


def _get_stats(symbol: str) -> dict:
    return STATS.get(symbol, {"win_rate": 0.55, "avg_win": 0.02, "avg_loss": 0.01})


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


async def generate_signal(redis: aioredis.Redis, symbol: str) -> dict | None:
    context_raw = await redis.get(f"context:latest:{symbol}")
    agents_raw = await redis.get(f"agents:verdicts:{symbol}")
    features_raw = await redis.get(f"features:latest:{symbol}")

    # context is optional but helpful; features are required for fallback
    context = json.loads(context_raw) if context_raw else {}
    agent_verdicts = json.loads(agents_raw) if agents_raw else []
    features = json.loads(features_raw) if features_raw else None

    # Need at least features to generate a signal
    if not features:
        return None

    stats = _get_stats(symbol)
    kelly_fraction = kelly.calculate(
        stats["win_rate"], stats["avg_win"], stats["avg_loss"], max_fraction=0.05
    )

    signal = generator.generate(symbol, agent_verdicts, kelly_fraction, features)
    if signal is None:
        return None

    signal_dict = {
        "symbol": symbol,
        "direction": signal.direction,
        "confidence": signal.confidence,
        "kelly_fraction": signal.kelly_fraction,
        "source": signal.source,
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

    # Always return for dashboard/scanner visibility; OMS filters by is_valid
    return signal_dict


async def main():
    log.info("signal_engine starting — dynamic symbol discovery")
    redis = await aioredis.from_url(REDIS_URL)

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

    active_set: set[str] = set(active_symbols)
    last_refresh = time.time()
    cycle = 0

    while True:
        # Periodically refresh symbol list
        if time.time() - last_refresh > SYMBOL_REFRESH_INTERVAL:
            new_symbols = await discover_symbols(redis)
            if new_symbols:
                active_set = set(new_symbols)
            last_refresh = time.time()

        signal_count = 0
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

        for sig in all_sigs:
            if sig["direction"] != "flat" and sig.get("is_valid"):
                signal_count += 1
                log.info(f"[{sig['symbol']}] {sig['direction'].upper()} conf={sig['confidence']:.2f} src={sig['source']}")
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
        if cycle % 12 == 0:  # every ~60 seconds
            long_c = sum(1 for s in all_sigs if s["direction"] == "long" and s.get("is_valid"))
            short_c = sum(1 for s in all_sigs if s["direction"] == "short" and s.get("is_valid"))
            log.info(f"Cycle {cycle}: {len(active_set)} symbols, {signal_count} active signals")

            # Push scan summary to activity feed
            await push_activity(redis, {
                "type": "scan_summary",
                "total": len(active_set),
                "long": long_c,
                "short": short_c,
                "flat": len(all_sigs) - long_c - short_c,
            })

            # Push top RSI extremes (most oversold / overbought)
            extremes = sorted(
                [s for s in all_sigs if s.get("rsi") is not None and (s["rsi"] < 32 or s["rsi"] > 68)],
                key=lambda s: abs(s["rsi"] - 50),
                reverse=True,
            )[:5]
            for s in extremes:
                rsi = s["rsi"]
                await push_activity(redis, {
                    "type": "rsi_alert",
                    "symbol": s["symbol"],
                    "direction": s["direction"],
                    "confidence": s["confidence"],
                    "source": "rsi_scan",
                    "rsi": rsi,
                    "label": "Aşırı Satış" if rsi < 32 else "Aşırı Alış",
                })

        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
