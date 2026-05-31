"""Persist shadow closed trades to PostgreSQL (same schema as OMS)."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    "postgresql://prometheus:password@postgres:5432/prometheus_trading",
)
_ENABLED = os.getenv("TRADES_POSTGRES_WRITE", "true").lower() in ("1", "true", "yes")
_pool = None


async def _pool_get():
    global _pool
    if _pool is not None:
        return _pool
    if not _ENABLED or not POSTGRES_URL:
        return None
    try:
        import asyncpg
        _pool = await asyncpg.create_pool(POSTGRES_URL, min_size=1, max_size=2, command_timeout=20)
        logger.info("Shadow trade_store Postgres pool ready")
    except Exception as e:
        logger.warning(f"trade_store pool failed: {e}")
        _pool = None
    return _pool


def _side(direction: str) -> str:
    return "LONG" if direction == "long" else "SHORT"


async def save_closed_trade(trade: dict) -> None:
    if not _ENABLED:
        return
    pool = await _pool_get()
    if not pool:
        return

    symbol = trade.get("symbol", "")
    direction = trade.get("direction", "long")
    closed_at = float(trade.get("closed_at", time.time()))
    hold_sec = float(trade.get("hold_seconds", 0))
    exit_ts = datetime.fromtimestamp(closed_at, tz=timezone.utc)
    entry_ts = datetime.fromtimestamp(max(0, closed_at - hold_sec), tz=timezone.utc)

    shadow_id = trade.get("shadow_id")
    trade_id = trade.get("trade_id") or f"{shadow_id}_{symbol}_{int(closed_at)}"

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO trades (
                    trade_id, symbol, side, entry_price, exit_price,
                    pnl_usdt, pnl_pct, entry_time, exit_time,
                    is_shadow, shadow_id, signal_source, confidence,
                    regime_at_entry, drift_at_entry, crisis_level
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9,
                    TRUE, $10, $11, $12, NULL, NULL, 0
                )
                ON CONFLICT (trade_id) DO NOTHING
                """,
                trade_id,
                symbol,
                _side(direction),
                trade.get("entry_price"),
                trade.get("exit_price"),
                trade.get("pnl_usdt"),
                trade.get("pnl_pct"),
                entry_ts,
                exit_ts,
                shadow_id,
                "shadow_system",
                trade.get("confidence"),
            )
    except Exception as e:
        logger.debug(f"trade_store skip {trade_id}: {e}")


def schedule_save(trade: dict) -> None:
    import asyncio
    try:
        asyncio.get_running_loop().create_task(save_closed_trade(trade))
    except RuntimeError:
        pass
