"""
Feedback Writer — Phase 3 (corrected).
Pipeline: shadow closes trade → autopsy calls write_feedback → here.

What this does:
1. Reads entry-time feature vector from ml:entry_features:{symbol}
   (snapshot taken by signal_engine at signal time — NOT the current features)
2. Appends labeled training sample to ml:training_data (online_learner retrains from there)
3. Updates per-agent accuracy by regime
4. Converts accuracy → agents:learned_weights (consumed by regime_router in agent_system)

IMPORTANT: Does NOT re-publish to ch:trade_closed — that would create an infinite loop
since autopsy itself subscribes to that channel.
"""
import json
import logging
import time

import redis.asyncio as aioredis

log = logging.getLogger(__name__)

TRAINING_DATA_KEY    = "ml:training_data"
TRAINING_DATA_MAX    = 2000
LEARNED_WEIGHTS_KEY  = "agents:learned_weights"
AGENT_ACCURACY_KEY   = "agents:accuracy"        # hash: agent → {accuracy, total_trades}

# Default weights — kept in sync with DebateAgent.DEFAULT_WEIGHTS
_DEFAULT_WEIGHTS = {
    "technical": 1.0, "onchain": 1.2, "sentiment": 0.8,
    "macro": 0.9, "news": 0.8, "bull": 1.0, "bear": 1.0,
    "neutral": 0.7, "risk": 1.1,
}

ACCURACY_UPDATE_EVERY = 5   # update learned_weights after every N feedback calls
_feedback_count = 0


async def write_feedback(
    redis: aioredis.Redis,
    trade: dict,
    analysis: dict,
) -> None:
    global _feedback_count

    symbol    = trade.get("symbol", "")
    pnl_pct   = float(trade.get("pnl_pct", 0))
    direction = trade.get("direction", "flat")
    regime    = trade.get("regime", "unknown")

    if not symbol or direction == "flat":
        return

    # ── 1. Build labeled ML training sample ──────────────────────────────
    # Read the feature vector snapshotted by signal_engine at entry time.
    # This key has a 4h TTL and is only written when a non-flat signal fires —
    # so it won't be stale from the current cycle.
    entry_raw = await redis.get(f"ml:entry_features:{symbol}")
    if entry_raw:
        try:
            feature_vec = json.loads(entry_raw)
            # Label: long_win=1, short_win=2, any_loss=0
            if direction == "long":
                label = 1 if pnl_pct > 0 else 0
            else:
                label = 2 if pnl_pct > 0 else 0

            sample = {
                "features": feature_vec,
                "label": label,
                "symbol": symbol,
                "pnl_pct": round(pnl_pct, 6),
                "direction": direction,
                "regime": regime,
                "ts": time.time(),
            }
            await redis.lpush(TRAINING_DATA_KEY, json.dumps(sample))
            await redis.ltrim(TRAINING_DATA_KEY, 0, TRAINING_DATA_MAX - 1)
            log.debug(
                f"FeedbackWriter: {symbol} {direction} label={label} "
                f"pnl={pnl_pct:.2%} → training sample added "
                f"(total={await redis.llen(TRAINING_DATA_KEY)})"
            )
        except Exception as e:
            log.warning(f"FeedbackWriter: training sample error for {symbol}: {e}")

    # ── 2. Per-agent accuracy tracking ────────────────────────────────────
    agent_votes = trade.get("agent_votes", [])
    if not agent_votes:
        _feedback_count += 1
        return

    win = pnl_pct > 0
    pipe = redis.pipeline()

    for vote in agent_votes:
        agent  = vote.get("agent", "")
        signal = vote.get("signal", "flat")
        if not agent:
            continue

        # Correct = predicted the right direction AND trade was profitable,
        #        OR voted flat/opposite AND trade lost (correctly avoided)
        correct = (
            (signal == direction and win) or
            (signal != direction and signal != "flat" and not win)
        )

        key = f"agents:accuracy:{agent}:{regime}"
        stats_raw = await redis.get(key)
        stats = json.loads(stats_raw) if stats_raw else {
            "correct": 0, "total": 0, "accuracy": 0.5,
        }
        stats["total"]   += 1
        if correct:
            stats["correct"] += 1
        stats["accuracy"]      = round(stats["correct"] / max(stats["total"], 1), 4)
        stats["last_updated"]  = time.time()
        pipe.set(key, json.dumps(stats), ex=86400 * 30)

    await pipe.execute()

    # Aggregate across regimes → update global accuracy hash
    all_agents = {v.get("agent") for v in agent_votes if v.get("agent")}
    agg_pipe = redis.pipeline()
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
            agg_pipe.hset(AGENT_ACCURACY_KEY, agent, json.dumps({
                "accuracy": round(total_c / total_t, 4),
                "total_trades": total_t,
            }))
    await agg_pipe.execute()

    _feedback_count += 1

    # ── 3. Accuracy → learned weights (every N calls) ─────────────────────
    if _feedback_count % ACCURACY_UPDATE_EVERY == 0:
        await _update_learned_weights(redis)

    log.debug(
        f"FeedbackWriter: {symbol} {direction} pnl={pnl_pct:.2%} "
        f"win={win} — {len(agent_votes)} agents tracked"
    )


async def _update_learned_weights(redis: aioredis.Redis) -> None:
    """
    Convert per-agent accuracy into weight adjustments.
    Agents with accuracy > 0.60 earn a 3% boost; < 0.45 earn a 3% penalty.
    Requires ≥10 trades before adjusting a weight (prevent noise).
    Writes to agents:learned_weights — regime_router in agent_system applies
    additional regime multipliers on top of these before using them.
    """
    try:
        # Load current learned weights (or defaults)
        raw = await redis.get(LEARNED_WEIGHTS_KEY)
        weights = json.loads(raw) if raw else dict(_DEFAULT_WEIGHTS)

        acc_data = await redis.hgetall(AGENT_ACCURACY_KEY)
        if not acc_data:
            return

        updated = False
        for agent_b, stats_b in acc_data.items():
            agent = agent_b.decode() if isinstance(agent_b, bytes) else agent_b
            stats = json.loads(stats_b.decode() if isinstance(stats_b, bytes) else stats_b)

            accuracy    = float(stats.get("accuracy", 0.5))
            total_trades = int(stats.get("total_trades", 0))

            if total_trades < 10:
                continue  # not enough data yet

            current = weights.get(agent, _DEFAULT_WEIGHTS.get(agent, 1.0))

            if accuracy > 0.60:
                weights[agent] = round(min(2.0, current * 1.03), 4)
                updated = True
            elif accuracy < 0.45:
                weights[agent] = round(max(0.3, current * 0.97), 4)
                updated = True

        if updated:
            await redis.set(LEARNED_WEIGHTS_KEY, json.dumps(weights), ex=3600 * 24)
            log.info(
                f"FeedbackWriter: learned weights updated — "
                f"{', '.join(f'{k}={v:.3f}' for k, v in sorted(weights.items()))}"
            )
    except Exception as e:
        log.error(f"FeedbackWriter: weight update error: {e}")
