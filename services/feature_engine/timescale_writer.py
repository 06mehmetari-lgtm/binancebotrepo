"""Async TimescaleDB feature persistence — enables NEAT/RL/backtest on real history."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

TIMESCALE_URL = os.getenv(
    "TIMESCALE_URL",
    "postgresql://prometheus:password@timescaledb:5432/prometheus_timeseries",
)
_ENABLED = os.getenv("FEATURES_TIMESCALE_WRITE", "true").lower() in ("1", "true", "yes")
_pool = None


async def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    try:
        import asyncpg
        _pool = await asyncpg.create_pool(TIMESCALE_URL, min_size=1, max_size=3, command_timeout=30)
        logger.info("Timescale feature writer pool ready")
    except Exception as e:
        logger.warning(f"Timescale pool unavailable: {e}")
        _pool = None
    return _pool


async def write_feature_row(symbol: str, features: dict, context: dict | None = None):
    if not _ENABLED:
        return
    pool = await _get_pool()
    if not pool:
        return
    ctx = context or {}
    now = datetime.now(timezone.utc)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO features (
                    time, symbol, rsi_14, rsi_7, macd_hist, bb_position, atr_14, adx_14,
                    imbalance_1, imbalance_5, imbalance_10, fear_greed_norm, vix_level,
                    drift_status, crisis_level, regime_id
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                """,
                now,
                symbol,
                features.get("rsi_14"),
                features.get("rsi_7"),
                features.get("macd_hist"),
                features.get("bb_position"),
                features.get("atr_14"),
                features.get("adx_14"),
                features.get("imbalance_1"),
                features.get("imbalance_5"),
                features.get("imbalance_10"),
                features.get("fear_greed_norm"),
                features.get("vix_level") or ctx.get("vix_level"),
                features.get("drift_status", "STABLE"),
                ctx.get("crisis_level", 0),
                str(ctx.get("regime", "unknown"))[:10],
            )
    except Exception as e:
        logger.debug(f"Timescale insert skip {symbol}: {e}")


def schedule_write(symbol: str, features: dict, context: dict | None = None):
    """Fire-and-forget — must not block hot path."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(write_feature_row(symbol, features, context))
    except RuntimeError:
        pass
