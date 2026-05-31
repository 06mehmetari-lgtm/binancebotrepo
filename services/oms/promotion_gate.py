"""
Live trading gate — OMS may only execute real orders when shadow promotion approves.
Requires DRY_RUN=false AND LIVE_TRADING_CONFIRMED=true AND system:promotion:status.approved.
"""

from __future__ import annotations

import json
import os

import redis.asyncio as aioredis

DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")
LIVE_CONFIRMED = os.getenv("LIVE_TRADING_CONFIRMED", "false").lower() in ("1", "true", "yes")
PROMOTION_KEY = "system:promotion:status"


async def check_live_trading_allowed(redis: aioredis.Redis) -> tuple[bool, str]:
    if DRY_RUN:
        return True, "dry_run_paper"

    if not LIVE_CONFIRMED:
        return False, "Set LIVE_TRADING_CONFIRMED=true after manual review"

    raw = await redis.get(PROMOTION_KEY)
    if not raw:
        return False, "Shadow promotion status missing — wait for shadow_system report_loop"

    try:
        status = json.loads(raw)
    except json.JSONDecodeError:
        return False, "Invalid promotion status payload"

    if not status.get("approved"):
        return False, status.get("reason", "Shadow promotion criteria not met")

    return True, f"live_allowed:{status.get('best_shadow_id', 'unknown')}"
