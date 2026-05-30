import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from signal_generator import SignalGenerator, Signal
from kelly_calculator import KellyCalculator
from signal_validator import SignalValidator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOLS_RAW = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
SYMBOLS = [s.strip() for s in SYMBOLS_RAW.split(",") if s.strip()]

generator = SignalGenerator()
kelly = KellyCalculator()
validator = SignalValidator()

# Running stats per symbol for Kelly (updated from trade results)
STATS: dict[str, dict] = {s: {"win_rate": 0.55, "avg_win": 0.02, "avg_loss": 0.01} for s in SYMBOLS}


async def generate_signal(redis: aioredis.Redis, symbol: str) -> dict | None:
    # Read agent verdicts and context
    context_raw = await redis.get(f"context:latest:{symbol}")
    agents_raw = await redis.get(f"agents:verdicts:{symbol}")

    if not context_raw:
        return None

    context = json.loads(context_raw)
    agent_verdicts = json.loads(agents_raw) if agents_raw else []

    # Kelly fraction
    stats = STATS[symbol]
    kelly_fraction = kelly.calculate(
        stats["win_rate"], stats["avg_win"], stats["avg_loss"], max_fraction=0.05
    )

    # Generate signal
    signal = generator.generate(agent_verdicts, kelly_fraction)
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
        "drift_status": context.get("drift_status", "STABLE"),
        "regime": context.get("regime", "unknown"),
    }

    # Validate
    is_valid, reason = validator.validate(signal_dict, context)
    if not is_valid:
        log.debug(f"Signal rejected for {symbol}: {reason}")
        return None

    return signal_dict


async def main():
    log.info(f"signal_engine starting — symbols: {SYMBOLS}")
    redis = await aioredis.from_url(REDIS_URL)

    while True:
        for symbol in SYMBOLS:
            sig = await generate_signal(redis, symbol)
            if sig:
                await redis.set(f"signal:latest:{symbol}", json.dumps(sig), ex=60)
                await redis.publish(f"ch:signal:{symbol}", symbol)
                log.info(f"Signal: {symbol} {sig['direction']} conf={sig['confidence']:.2f}")
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
