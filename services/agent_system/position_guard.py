"""
AI Position Guard — sürekli açık pozisyon izleme (saniye bazlı).

Açık pozisyonlar evren taramasından önce işlenir; acil çıkış kuralları + taze debate.
OMS/shadow `ch:position:guard` ile kapatma tetikler.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, asdict

import redis.asyncio as aioredis

log = logging.getLogger(__name__)

GUARD_CHANNEL = "ch:position:guard"
GUARD_STATUS_KEY = "guard:status:v1"

# Eşikler (paper test için sıkı; canlıda immunity ayrıca korur)
MAX_LOSS_PCT = float(os.getenv("GUARD_MAX_LOSS_PCT", "1.5"))
EMERGENCY_LOSS_PCT = float(os.getenv("GUARD_EMERGENCY_LOSS_PCT", "2.5"))
MIN_HOLD_CONFIDENCE = float(os.getenv("GUARD_MIN_HOLD_CONFIDENCE", "0.45"))
GUARD_DEBATE_MAX_AGE = float(os.getenv("GUARD_DEBATE_MAX_AGE", "8"))
GUARD_ACTION_COOLDOWN = float(os.getenv("GUARD_ACTION_COOLDOWN", "30"))
_guard_sem: asyncio.Semaphore | None = None
_last_close_publish: dict[str, float] = {}


def _guard_semaphore() -> asyncio.Semaphore:
    global _guard_sem
    if _guard_sem is None:
        n = int(os.getenv("GUARD_DEBATE_CONCURRENCY", "2"))
        _guard_sem = asyncio.Semaphore(max(1, n))
    return _guard_sem


async def _verdict_is_fresh(redis: aioredis.Redis, symbol: str) -> bool:
    raw = await redis.get(f"agents:verdict:{symbol}")
    if not raw:
        return False
    try:
        v = json.loads(raw)
        ts = float(v.get("timestamp", 0))
        return ts > 0 and (time.time() - ts) < GUARD_DEBATE_MAX_AGE
    except (json.JSONDecodeError, TypeError, ValueError):
        return False


@dataclass
class GuardDecision:
    symbol: str
    source: str
    direction: str
    action: str  # hold | close | emergency_close
    urgency: str  # low | medium | high | critical
    reason: str
    unrealized_pct: float
    ai_confidence: float
    trade_action: str
    checks: dict
    ts: float
    shadow_id: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if not d.get("shadow_id"):
            d.pop("shadow_id", None)
        return d


def _mid_from_ticker(raw: str | None) -> float:
    if not raw:
        return 0.0
    try:
        t = json.loads(raw)
        d = t.get("data", t)
        bid = float(d.get("b", 0) or 0)
        ask = float(d.get("a", bid) or bid)
        return (bid + ask) / 2 if bid else ask
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0.0


def _unrealized_pct(direction: str, entry: float, price: float) -> float:
    if entry <= 0 or price <= 0:
        return 0.0
    if direction == "long":
        return (price - entry) / entry * 100
    return (entry - price) / entry * 100


def evaluate_position(
    symbol: str,
    pos: dict,
    features: dict,
    context: dict,
    signal: dict | None,
    verdict: dict | None,
    learn: dict | None,
) -> GuardDecision:
    direction = str(pos.get("direction", "long"))
    entry = float(pos.get("entry_price") or pos.get("price") or 0)
    price = float(features.get("close") or features.get("last_price") or entry)
    source = str(pos.get("source", "oms"))
    upnl = _unrealized_pct(direction, entry, price)

    crisis = int(context.get("crisis_level", 0) or 0)
    drift = str(context.get("drift_status", features.get("drift_status", "STABLE")))
    sig_dir = str((signal or {}).get("direction", "flat"))
    sig_conf = float((signal or {}).get("confidence", 0) or 0)
    trade_action = str((signal or {}).get("trade_action", "none"))
    v_dir = str((verdict or {}).get("direction", "flat"))
    v_conf = float((verdict or {}).get("confidence", 0) or 0)
    avoid = str((learn or {}).get("avoid_hint", "") or "")

    checks: dict = {
        "crisis": crisis,
        "drift": drift,
        "signal": sig_dir,
        "verdict": v_dir,
        "upnl_pct": round(upnl, 3),
    }

    action = "hold"
    urgency = "low"
    reason = f"İzleniyor — AI güven {v_conf:.0%}, PnL {upnl:+.2f}%"

    if crisis >= 4 or drift == "SHOCK":
        return GuardDecision(
            symbol, source, direction, "emergency_close", "critical",
            f"Kriz L{crisis} / drift {drift} — anında çıkış",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    if upnl <= -EMERGENCY_LOSS_PCT:
        return GuardDecision(
            symbol, source, direction, "emergency_close", "critical",
            f"Acil zarar limiti %{EMERGENCY_LOSS_PCT} aşıldı ({upnl:.2f}%)",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    try:
        from risk_limits import get_active_limits
        flat_close_conf = get_active_limits().min_signal_confidence * 0.92
    except Exception:
        flat_close_conf = 0.55
    if trade_action == "close" or (
        sig_dir == "flat" and v_dir == "flat" and v_conf >= flat_close_conf
    ):
        return GuardDecision(
            symbol, source, direction, "close", "high",
            "AI çıkış (FLAT) — sinyal ve verdict uyumlu",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    if v_dir == "flat" and direction in ("long", "short"):
        return GuardDecision(
            symbol, source, direction, "close", "high",
            f"AI FLAT ({v_conf:.0%}) — yön uyumsuz pozisyon kapatılıyor",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    try:
        from risk_limits import get_active_limits
        reverse_conf = get_active_limits().min_signal_confidence
    except Exception:
        reverse_conf = 0.6
    if v_dir in ("long", "short") and v_dir != direction and v_conf >= reverse_conf:
        return GuardDecision(
            symbol, source, direction, "close", "high",
            f"AI yön tersine döndü ({v_dir.upper()} {v_conf:.0%})",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    if upnl <= -MAX_LOSS_PCT:
        return GuardDecision(
            symbol, source, direction, "close", "high",
            f"Koruyucu zarar kes %{MAX_LOSS_PCT} ({upnl:.2f}%)",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    if crisis >= 2 and upnl < 0:
        return GuardDecision(
            symbol, source, direction, "close", "medium",
            f"Kriz L{crisis} + negatif PnL — risk azalt",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    # learn:profile avoid_hint is for new entries (signal sizing), not micro-loss exits
    if avoid and upnl <= -MAX_LOSS_PCT and len(avoid) > 5:
        low = avoid.lower()
        entry_only = (
            "agresif boyut",
            "açma:",
            "long açma",
            "short açma",
            "chase",
            "crowded long",
        )
        if not any(p in low for p in entry_only):
            return GuardDecision(
                symbol, source, direction, "close", "medium",
                f"Öğrenme kaçınma + zarar %{abs(upnl):.2f}: {avoid[:80]}",
                upnl, v_conf, trade_action, checks, time.time(),
            )

    if v_conf < MIN_HOLD_CONFIDENCE and upnl < 0:
        urgency = "medium"
        reason = f"Düşük AI güven ({v_conf:.0%}) + zarar — sıkı izleme"

    return GuardDecision(
        symbol, source, direction, action, urgency, reason,
        upnl, v_conf, trade_action, checks, time.time(),
    )


def _position_key(pos: dict) -> tuple[str, str, str]:
    return (
        str(pos.get("symbol", "")).upper(),
        str(pos.get("source", "oms")),
        str(pos.get("shadow_id", "")),
    )


def _dedupe_positions(positions: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for pos in positions:
        key = _position_key(pos)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        out.append(pos)
    return out


async def list_open_positions(redis: aioredis.Redis) -> list[dict]:
    raw = await redis.get("portfolio:state:v1")
    if raw:
        try:
            state = json.loads(raw)
            return _dedupe_positions(list(state.get("positions") or []))
        except json.JSONDecodeError:
            pass
    positions: list[dict] = []
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="oms:position:*", count=50)
        for key in keys:
            k = key.decode() if isinstance(key, bytes) else key
            sym = k.split(":")[-1]
            pr = await redis.get(k)
            if pr:
                try:
                    p = json.loads(pr)
                    p["symbol"] = sym
                    p["source"] = "oms"
                    positions.append(p)
                except json.JSONDecodeError:
                    pass
        if cursor == 0:
            break
    return _dedupe_positions(positions)


async def run_guard_cycle(
    redis: aioredis.Redis,
    debate_fn,
) -> list[GuardDecision]:
    """Tek tur: tüm açık pozisyonlarda debate + değerlendirme."""
    positions = await list_open_positions(redis)
    if not positions:
        await redis.set(
            GUARD_STATUS_KEY,
            json.dumps({"active": False, "count": 0, "updated_at": time.time()}),
            ex=30,
        )
        return []

    decisions: list[GuardDecision] = []

    for pos in positions:
        symbol = str(pos.get("symbol", ""))
        if not symbol.endswith("USDT"):
            continue
        if not await _verdict_is_fresh(redis, symbol):
            try:
                async with _guard_semaphore():
                    await debate_fn(redis, symbol)
            except Exception as e:
                log.debug(f"guard debate {symbol}: {e}")

        pipe = redis.pipeline()
        pipe.get(f"features:latest:{symbol}")
        pipe.get(f"context:latest:{symbol}")
        pipe.get(f"signal:latest:{symbol}")
        pipe.get(f"agents:verdict:{symbol}")
        pipe.get(f"learn:profile:{symbol}")
        pipe.get(f"binance:ticker:{symbol.lower()}")
        res = await pipe.execute()

        try:
            features = json.loads(res[0]) if res[0] else {}
            context = json.loads(res[1]) if res[1] else {}
            signal = json.loads(res[2]) if res[2] else None
            verdict = json.loads(res[3]) if res[3] else None
            learn = json.loads(res[4]) if res[4] else None
            if res[5]:
                mid = _mid_from_ticker(res[5])
                if mid > 0:
                    features["close"] = mid
        except json.JSONDecodeError:
            continue

        pos["source"] = pos.get("source", "oms")
        dec = evaluate_position(symbol, pos, features, context, signal, verdict, learn)
        if pos.get("source") == "shadow":
            dec.shadow_id = str(pos.get("shadow_id", ""))
        decisions.append(dec)

        await redis.set(f"guard:position:{symbol}", json.dumps(dec.to_dict()), ex=120)

        if dec.action in ("close", "emergency_close"):
            pub_key = f"{symbol}:{dec.source}:{dec.shadow_id}"
            now = time.time()
            if now - _last_close_publish.get(pub_key, 0) < GUARD_ACTION_COOLDOWN:
                continue
            _last_close_publish[pub_key] = now
            await redis.publish(GUARD_CHANNEL, json.dumps(dec.to_dict()))
            log.warning(
                f"[GUARD] {symbol} {dec.action} ({dec.urgency}) — {dec.reason}"
            )

    status = {
        "active": True,
        "count": len(decisions),
        "updated_at": time.time(),
        "positions": [
            {
                "symbol": d.symbol,
                "action": d.action,
                "urgency": d.urgency,
                "upnl_pct": d.unrealized_pct,
                "ai_confidence": d.ai_confidence,
            }
            for d in decisions
        ],
    }
    await redis.set(GUARD_STATUS_KEY, json.dumps(status), ex=60)
    return decisions


async def position_guard_loop(redis: aioredis.Redis, debate_fn) -> None:
    interval = float(os.getenv("POSITION_GUARD_SEC", "1.0"))
    log.info(
        f"position_guard active — every {interval}s "
        f"(debate refresh >{GUARD_DEBATE_MAX_AGE}s)"
    )
    while True:
        try:
            await run_guard_cycle(redis, debate_fn)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception(f"position_guard cycle: {e}")
            await asyncio.sleep(min(interval, 5.0))
