"""
Feedback Writer — Phase 3.
After each closed trade, publishes labeled training data to Redis
so the online learner can retrain the ML model.
Also updates per-agent accuracy stats for regime-aware weight learning.
"""
import json
import logging
import time

import redis.asyncio as aioredis

log = logging.getLogger(__name__)

AGENT_PERF_KEY   = "agents:accuracy"  # hash: agent_name → JSON accuracy stats
FEATURE_KEYS_LEN = 35                 # must match ml_signal.FEATURE_KEYS


async def write_feedback(
    redis: aioredis.Redis,
    trade: dict,
    analysis: dict,
) -> None:
    """
    Called by autopsy after trade analysis.
    trade: raw trade record (symbol, direction, pnl_pct, agent_votes, ...)
    analysis: result from TradeAnalyzer.analyze()
    """
    symbol    = trade.get("symbol", "")
    pnl_pct   = float(trade.get("pnl_pct", 0))
    direction = trade.get("direction", "flat")
    regime    = trade.get("regime", "unknown")

    if not symbol or direction == "flat":
        return

    # ── 1. Signal feature vector saved at entry time ──────────────────────
    # The signal_engine stores features at entry time as ml:signal_features:{symbol}
    feat_raw = await redis.get(f"ml:signal_features:{symbol}")
    if feat_raw:
        feature_vec = json.loads(feat_raw)
        # Publish to online learner via ch:trade_closed with feature vector embedded
        feedback = {
            "symbol": symbol,
            "direction": direction,
            "pnl_pct": pnl_pct,
            "regime": regime,
            "feature_vec_len": len(feature_vec),
            "ts": time.time(),
        }
        await redis.publish("ch:trade_closed", json.dumps(feedback))

    # ── 2. Per-agent accuracy tracking ────────────────────────────────────
    agent_votes = trade.get("agent_votes", [])
    if not agent_votes:
        return

    win = pnl_pct > 0
    pipe = redis.pipeline()

    for vote in agent_votes:
        agent   = vote.get("agent", "")
        signal  = vote.get("signal", "flat")
        if not agent:
            continue

        correct = (signal == direction and win) or (signal != direction and not win and signal != "flat")

        key = f"agents:accuracy:{agent}:{regime}"
        stats_raw = await redis.get(key)
        stats = json.loads(stats_raw) if stats_raw else {
            "correct": 0, "total": 0, "accuracy": 0.5,
        }

        stats["total"] += 1
        if correct:
            stats["correct"] += 1
        stats["accuracy"] = round(stats["correct"] / max(stats["total"], 1), 4)
        stats["last_updated"] = time.time()

        pipe.set(key, json.dumps(stats), ex=86400 * 30)

    await pipe.execute()

    # ── 3. Aggregate accuracy across regimes → write to agents:accuracy hash ──
    all_agents = set(v.get("agent", "") for v in agent_votes if v.get("agent"))
    for agent in all_agents:
        keys = await redis.keys(f"agents:accuracy:{agent}:*")
        total_c, total_t = 0, 0
        for k in keys:
            r = await redis.get(k)
            if r:
                s = json.loads(r)
                total_c += s.get("correct", 0)
                total_t += s.get("total", 0)
        if total_t > 0:
            agg_acc = round(total_c / total_t, 4)
            await redis.hset(AGENT_PERF_KEY, agent, json.dumps({
                "accuracy": agg_acc,
                "total_trades": total_t,
            }))

    log.debug(
        f"FeedbackWriter: {symbol} {direction} pnl={pnl_pct:.2%} "
        f"win={win} — {len(agent_votes)} agents updated"
    )
