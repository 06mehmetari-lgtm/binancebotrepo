"""
Dynamic risk limits — Postgres (source of truth) + Redis cache for all services.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

REDIS_KEY = "system:risk_limits:v1"
REDIS_CHANNEL = "ch:risk_limits:updated"

DEFAULTS: dict[str, float | int] = {
    "max_leverage": 3.0,
    "max_position_pct": 0.05,
    "max_daily_loss_pct": 0.02,
    "max_open_positions": 3,
    "min_signal_confidence": 0.60,
    "min_immunity_confidence": 0.52,
    "max_trades_per_day": 50,
}


@dataclass
class RiskLimits:
    max_leverage: float = 3.0
    max_position_pct: float = 0.05
    max_daily_loss_pct: float = 0.02
    max_open_positions: int = 3
    min_signal_confidence: float = 0.60
    min_immunity_confidence: float = 0.52
    max_trades_per_day: int = 50
    updated_at: float = 0.0
    updated_by: str = "system"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RiskLimits:
        return cls(
            max_leverage=float(raw.get("max_leverage", DEFAULTS["max_leverage"])),
            max_position_pct=float(raw.get("max_position_pct", DEFAULTS["max_position_pct"])),
            max_daily_loss_pct=float(raw.get("max_daily_loss_pct", DEFAULTS["max_daily_loss_pct"])),
            max_open_positions=int(raw.get("max_open_positions", DEFAULTS["max_open_positions"])),
            min_signal_confidence=float(
                raw.get("min_signal_confidence", DEFAULTS["min_signal_confidence"])
            ),
            min_immunity_confidence=float(
                raw.get("min_immunity_confidence", DEFAULTS["min_immunity_confidence"])
            ),
            max_trades_per_day=int(raw.get("max_trades_per_day", DEFAULTS["max_trades_per_day"])),
            updated_at=float(raw.get("updated_at", time.time())),
            updated_by=str(raw.get("updated_by", "system")),
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not 1 <= self.max_leverage <= 125:
            errors.append("max_leverage 1–125 arası olmalı")
        if not 0.001 <= self.max_position_pct <= 1.0:
            errors.append("max_position_pct 0.1%–100% arası (0.001–1.0)")
        if not 0.001 <= self.max_daily_loss_pct <= 1.0:
            errors.append("max_daily_loss_pct 0.1%–100% arası")
        if not 1 <= self.max_open_positions <= 500:
            errors.append("max_open_positions 1–500")
        if not 0.1 <= self.min_signal_confidence <= 1.0:
            errors.append("min_signal_confidence 0.1–1.0")
        if not 0.1 <= self.min_immunity_confidence <= 1.0:
            errors.append("min_immunity_confidence 0.1–1.0")
        if not 1 <= self.max_trades_per_day <= 10_000:
            errors.append("max_trades_per_day 1–10000")
        return errors


_active = RiskLimits()


def get_active_limits() -> RiskLimits:
    return _active


def set_active_limits(limits: RiskLimits) -> None:
    global _active
    _active = limits


def parse_redis_raw(raw: str | bytes | None) -> RiskLimits | None:
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return RiskLimits.from_dict(data)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning("risk_limits parse failed: %s", e)
    return None


def _row_to_limits(row: tuple) -> RiskLimits:
    return RiskLimits(
        max_leverage=float(row[0]),
        max_position_pct=float(row[1]),
        max_daily_loss_pct=float(row[2]),
        max_open_positions=int(row[3]),
        min_signal_confidence=float(row[4]),
        min_immunity_confidence=float(row[5]),
        max_trades_per_day=int(row[6]),
        updated_at=float(row[7] or time.time()),
        updated_by=str(row[8] or "system"),
    )


def load_from_postgres_sync() -> RiskLimits | None:
    """Postgres system_risk_limits — source of truth when dashboard saves."""
    url = os.getenv("POSTGRES_URL", "").strip()
    if not url:
        return None
    try:
        import psycopg2

        conn = psycopg2.connect(url)
        try:
            with conn.cursor() as cur:
                cur.execute(SELECT_SQL)
                row = cur.fetchone()
            if not row:
                return None
            limits = _row_to_limits(row)
            set_active_limits(limits)
            return limits
        finally:
            conn.close()
    except Exception as e:
        logger.warning("load_from_postgres failed: %s", e)
    return None


async def load_from_redis(redis) -> RiskLimits | None:
    try:
        raw = await redis.get(REDIS_KEY)
        parsed = parse_redis_raw(raw)
        if parsed:
            set_active_limits(parsed)
            return parsed
    except Exception as e:
        logger.warning("load_from_redis failed: %s", e)
    return None


async def bootstrap_limits(redis) -> RiskLimits:
    """Prefer Postgres (dashboard), sync to Redis, else Redis cache, else defaults."""
    pg = load_from_postgres_sync()
    if pg:
        await publish_to_redis(redis, pg)
        logger.info(
            "risk_limits from Postgres — open=%s daily_loss=%.1f%% signal_conf=%.0f%%",
            pg.max_open_positions,
            pg.max_daily_loss_pct * 100,
            pg.min_signal_confidence * 100,
        )
        return pg
    cached = await load_from_redis(redis)
    if cached:
        return cached
    return get_active_limits()


async def publish_to_redis(redis, limits: RiskLimits) -> None:
    payload = json.dumps(limits.to_dict())
    await redis.set(REDIS_KEY, payload)
    await redis.publish(REDIS_CHANNEL, payload)


UPSERT_SQL = """
INSERT INTO system_risk_limits (
  id, max_leverage, max_position_pct, max_daily_loss_pct, max_open_positions,
  min_signal_confidence, min_immunity_confidence, max_trades_per_day, updated_by
) VALUES (1, $1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (id) DO UPDATE SET
  max_leverage = EXCLUDED.max_leverage,
  max_position_pct = EXCLUDED.max_position_pct,
  max_daily_loss_pct = EXCLUDED.max_daily_loss_pct,
  max_open_positions = EXCLUDED.max_open_positions,
  min_signal_confidence = EXCLUDED.min_signal_confidence,
  min_immunity_confidence = EXCLUDED.min_immunity_confidence,
  max_trades_per_day = EXCLUDED.max_trades_per_day,
  updated_by = EXCLUDED.updated_by,
  updated_at = NOW()
RETURNING max_leverage, max_position_pct, max_daily_loss_pct, max_open_positions,
  min_signal_confidence, min_immunity_confidence, max_trades_per_day,
  EXTRACT(EPOCH FROM updated_at) AS updated_at, updated_by
"""

SELECT_SQL = """
SELECT max_leverage, max_position_pct, max_daily_loss_pct, max_open_positions,
  min_signal_confidence, min_immunity_confidence, max_trades_per_day,
  EXTRACT(EPOCH FROM updated_at) AS updated_at, updated_by
FROM system_risk_limits WHERE id = 1
"""
