import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from debate_agent import DebateAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOL_REFRESH_INTERVAL = 300

debate = DebateAgent()


async def discover_symbols(redis: aioredis.Redis) -> list[str]:
    keys = await redis.keys("features:latest:*")
    if not keys:
        return []
    return sorted(
        (k.decode() if isinstance(k, bytes) else k).replace("features:latest:", "").upper()
        for k in keys
    )


async def run_debate_for_symbol(redis: aioredis.Redis, symbol: str):
    feat_raw = await redis.get(f"features:latest:{symbol}")
    ctx_raw = await redis.get(f"context:latest:{symbol}")

    if not feat_raw or not ctx_raw:
        return

    features = json.loads(feat_raw)
    context = json.loads(ctx_raw)

    result = await debate.run_debate(symbol, features, context)

    # Serialize votes
    votes_payload = [
        {
            "agent": v.agent_name,
            "signal": v.signal,
            "confidence": v.confidence,
            "direction": v.signal,
        }
        for v in result.all_votes
    ]

    await redis.set(f"agents:verdicts:{symbol}", json.dumps(votes_payload), ex=60)

    # Also store final verdict for signal engine
    verdict = {
        "symbol": symbol,
        "direction": result.final_signal,
        "confidence": result.final_confidence,
        "consensus": result.consensus_strength,
        "reasoning": result.majority_reasoning,
        "vote_count": len(result.all_votes),
        "timestamp": time.time(),
    }
    await redis.set(f"agents:verdict:{symbol}", json.dumps(verdict), ex=60)
    await redis.publish(f"ch:agents:{symbol}", symbol)

    if result.final_signal != "flat":
        log.info(
            f"[{symbol}] {result.final_signal.upper()} conf={result.final_confidence:.2f} "
            f"consensus={result.consensus_strength:.0%} ({len(result.all_votes)} agents)"
        )


async def weight_update_loop(redis: aioredis.Redis):
    """Periodically load updated weights from Redis."""
    while True:
        weights_raw = await redis.get("agents:weights")
        if weights_raw:
            weights = json.loads(weights_raw)
            debate.weights.update(weights)
        await asyncio.sleep(300)


async def main():
    log.info("agent_system starting — 9-agent debate team — dynamic symbols")
    redis = await aioredis.from_url(REDIS_URL)

    active_set: set[str] = set()
    last_refresh = 0.0

    async def debate_loop():
        nonlocal active_set, last_refresh
        while True:
            now = time.time()
            if now - last_refresh > SYMBOL_REFRESH_INTERVAL or not active_set:
                syms = await discover_symbols(redis)
                if syms:
                    active_set = set(syms)
                    log.info(f"agent_system: {len(active_set)} symbols discovered")
                last_refresh = now

            for symbol in list(active_set):
                try:
                    await run_debate_for_symbol(redis, symbol)
                except Exception as e:
                    log.error(f"Debate error for {symbol}: {e}")
            await asyncio.sleep(10)

    await asyncio.gather(debate_loop(), weight_update_loop(redis))


if __name__ == "__main__":
    asyncio.run(main())
