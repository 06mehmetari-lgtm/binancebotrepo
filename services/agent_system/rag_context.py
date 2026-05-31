"""Load recent trade lessons from Redis (written by autopsy) for debate context."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


async def fetch_trade_lessons(redis, symbol: str, limit: int = 8) -> list[str]:
    """Return short lesson strings from trades, backtest, and live learning engine."""
    try:
        learn_raw = await redis.get(f"learn:profile:{symbol}")
        if learn_raw:
            try:
                prof = json.loads(learn_raw)
                stage = prof.get("learning_stage", "L0")
                ai = (prof.get("ai_insight") or "")[:200]
                hint = (
                    f"[Öğrenen AI {stage}] Rejim={prof.get('current_regime')} | "
                    f"Al:{prof.get('best_entry_hint', '')} | Kaçın:{prof.get('avoid_hint', '')}"
                    + (f" | {ai}" if ai else "")
                )
                lessons_prefill = [hint]
                for d in prof.get("drivers", [])[:2]:
                    lessons_prefill.append(
                        f"Faktör {d.get('factor')}: %{d.get('avg_move_pct', 0):.2f} "
                        f"(WR {float(d.get('win_rate', 0))*100:.0f}%)"
                    )
            except json.JSONDecodeError:
                lessons_prefill = []
        else:
            lessons_prefill = []

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
            text = data.get("text")
            if text:
                lessons.append(str(text))
            elif won:
                lessons.append(f"Önceki kazanç ({pnl:+.2%}) — {cat}")
            else:
                lessons.append(f"Önceki zarar ({pnl:+.2%}) — ders: {cat}")
        bt_raw = await redis.get(f"backtest:insights:{symbol}")
        if bt_raw:
            try:
                ins = json.loads(bt_raw)
                line = ins.get("direction_lesson") or ins.get("regime_note")
                if line and line not in lessons:
                    lessons.insert(0, f"[Backtest 1y] {line}")
            except json.JSONDecodeError:
                pass
        # Deduplicate while keeping learning profile on top
        seen: set[str] = set()
        merged: list[str] = []
        for line in lessons_prefill + lessons:
            if line and line not in seen:
                seen.add(line)
                merged.append(line)
        return merged[:limit]
    except Exception as e:
        logger.debug(f"trade lessons read failed for {symbol}: {e}")
        return []
