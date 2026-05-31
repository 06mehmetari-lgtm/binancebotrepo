"""Load recent trade lessons from Redis (written by autopsy) for debate context."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


async def fetch_trade_lessons(redis, symbol: str, limit: int = 5) -> list[str]:
    """Return short lesson strings from recent closed trades for this symbol."""
    try:
        raw = await redis.lrange(f"trade:lessons:{symbol}", 0, limit - 1)
        lessons: list[str] = []
        for item in raw or []:
            data = json.loads(item) if isinstance(item, (str, bytes)) else item
            if isinstance(data, bytes):
                data = json.loads(data.decode())
            if not isinstance(data, dict):
                continue
            cat = data.get("error_category", "")
            pnl = float(data.get("pnl_pct", 0) or 0)
            won = data.get("was_winner", pnl > 0)
            if won:
                lessons.append(f"Önceki kazanç ({pnl:+.2%}) — {cat}")
            else:
                lessons.append(f"Önceki zarar ({pnl:+.2%}) — ders: {cat}")
        return lessons
    except Exception as e:
        logger.debug(f"trade lessons read failed for {symbol}: {e}")
        return []
