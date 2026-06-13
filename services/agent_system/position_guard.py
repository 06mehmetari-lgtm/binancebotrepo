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

try:
    from profit_rules import (
        GUARD_EMERGENCY_LOSS_PCT as _PR_EMERGENCY,
        GUARD_MAX_LOSS_PCT as _PR_MAX_LOSS,
        GUARD_TAKE_PROFIT_PCT as _PR_TP,
        BREAKEVEN_ACTIVATE_PCT as _PR_BE_ACT,
        BREAKEVEN_FLOOR_PCT as _PR_BE_FLOOR,
        profit_tiers as _profit_tiers_from_rules,
    )
except ImportError:
    _PR_MAX_LOSS = 1.0
    _PR_EMERGENCY = 1.8
    _PR_TP = 1.2
    _PR_BE_ACT = 0.35
    _PR_BE_FLOOR = 0.08
    _profit_tiers_from_rules = None

# Eşikler — autopsy: %0.5 TP çok erken, -%8 zarar guard dışı kaldı
MAX_LOSS_PCT = float(os.getenv("GUARD_MAX_LOSS_PCT", str(_PR_MAX_LOSS)))
EMERGENCY_LOSS_PCT = float(os.getenv("GUARD_EMERGENCY_LOSS_PCT", str(_PR_EMERGENCY)))
MIN_HOLD_CONFIDENCE = float(os.getenv("GUARD_MIN_HOLD_CONFIDENCE", "0.45"))
GUARD_DEBATE_MAX_AGE = float(os.getenv("GUARD_DEBATE_MAX_AGE", "8"))
GUARD_ACTION_COOLDOWN = float(os.getenv("GUARD_ACTION_COOLDOWN", "15"))
TAKE_PROFIT_PCT = float(os.getenv("GUARD_TAKE_PROFIT_PCT", str(_PR_TP)))
PAPER_MIN_HOLD_SEC = float(os.getenv("PAPER_MIN_HOLD_SEC", "180"))
PROFIT_PROTECT_PCT = float(os.getenv("GUARD_PROFIT_PROTECT_PCT", "0.8"))
TRAIL_MIN_PEAK_PCT = float(os.getenv("GUARD_TRAIL_MIN_PEAK", "2.0"))
TRAIL_GIVEBACK_PCT = float(os.getenv("GUARD_TRAIL_GIVEBACK_PCT", "0.5"))
SYMBOL_COOLDOWN_SEC = int(os.getenv("SYMBOL_COOLDOWN_SEC", "1800"))
BREAKEVEN_ACTIVATE_PCT = float(os.getenv("BREAKEVEN_ACTIVATE_PCT", str(_PR_BE_ACT)))
BREAKEVEN_FLOOR_PCT = float(os.getenv("BREAKEVEN_FLOOR_PCT", str(_PR_BE_FLOOR)))


def _profit_tiers() -> list[float]:
    if _profit_tiers_from_rules:
        return _profit_tiers_from_rules()
    raw = os.getenv("GUARD_PROFIT_TIERS", "1.5,3,6,12")
    tiers = sorted({float(x.strip()) for x in raw.split(",") if x.strip()})
    return tiers or [0.5, 2.0, 5.0, 10.0, 25.0]
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

    try:
        from risk_limits import is_paper_unlimited
        paper_mode = is_paper_unlimited()
    except Exception:
        paper_mode = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")

    entry_time = float(pos.get("entry_time", 0) or pos.get("time", 0) or 0)
    hold_sec = time.time() - entry_time if entry_time > 0 else 9999.0

    checks: dict = {
        "crisis": crisis,
        "drift": drift,
        "signal": sig_dir,
        "verdict": v_dir,
        "upnl_pct": round(upnl, 3),
        "hold_sec": round(hold_sec, 0),
    }

    try:
        from profit_rules import (
            MAX_POSITION_HOLD_SEC,
            STALE_VERDICT_HOLD_SEC,
            conf_meets,
            is_blacklisted,
            stale_flat_should_exit,
            evaluate_position_exit,
            update_ladder_tracking,
            recovery_should_hold,
            LOSS_TO_PROFIT_TARGET_PCT,
        )
    except ImportError:
        MAX_POSITION_HOLD_SEC = 3600
        STALE_VERDICT_HOLD_SEC = 1200
        is_blacklisted = lambda _s: False  # noqa: E731
        conf_meets = lambda c, m: c >= m  # noqa: E731
        evaluate_position_exit = None  # type: ignore
        update_ladder_tracking = lambda l, u, h: dict(l or {})  # noqa: E731
        recovery_should_hold = lambda **_k: (False, "")  # noqa: E731
        LOSS_TO_PROFIT_TARGET_PCT = 0.05

    if is_blacklisted(symbol) and hold_sec >= 60:
        return GuardDecision(
            symbol, source, direction, "close", "high",
            "Blacklist sembol — pozisyon kapatılıyor",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    if hold_sec >= MAX_POSITION_HOLD_SEC:
        return GuardDecision(
            symbol, source, direction, "close", "medium",
            f"Max tutma {MAX_POSITION_HOLD_SEC // 60}dk — slot serbest (PnL {upnl:+.2f}%)",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    ladder = pos.get("ladder") or {}
    peak_upnl = float(ladder.get("peak_upnl_pct") or upnl)
    ladder = update_ladder_tracking(ladder, upnl, hold_sec)
    peak_upnl = float(ladder.get("peak_upnl_pct") or upnl)
    checks["bounce_pct"] = ladder.get("bounce_from_trough_pct")
    checks["recovery_armed"] = bool(ladder.get("recovery_armed"))

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

    if evaluate_position_exit is not None:
        smart_action, smart_reason, smart_kind = evaluate_position_exit(
            hold_sec=hold_sec,
            upnl=upnl,
            direction=direction,
            ladder=ladder,
            sl_pct=float(ladder.get("stop_loss_pct") or MAX_LOSS_PCT),
            tp_pct=float(ladder.get("take_profit_pct") or TAKE_PROFIT_PCT),
            sig_dir=sig_dir,
            sig_conf=sig_conf,
            v_dir=v_dir,
            v_conf=v_conf,
            crisis_level=crisis,
        )
        if smart_action in ("close", "emergency_close"):
            urg = "critical" if smart_action == "emergency_close" else (
                "high" if smart_kind in ("sl", "tp", "trail", "recovery_profit") else "medium"
            )
            return GuardDecision(
                symbol, source, direction, smart_action, urg,
                smart_reason,
                upnl, v_conf, trade_action, {**checks, "exit_kind": smart_kind}, time.time(),
            )

    if hold_sec >= STALE_VERDICT_HOLD_SEC and v_conf < 0.05:
        return GuardDecision(
            symbol, source, direction, "close", "medium",
            f"Agent verdict eski ({hold_sec:.0f}s) — pozisyon kapatılıyor",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    should_stale, stale_why = stale_flat_should_exit(
        hold_sec=hold_sec,
        upnl=upnl,
        peak_upnl=peak_upnl,
        sig_dir=sig_dir,
        direction=direction,
        v_dir=v_dir,
        v_conf=v_conf,
    )
    if should_stale:
        rec, rec_why = recovery_should_hold(
            hold_sec=hold_sec,
            upnl=upnl,
            peak_upnl=peak_upnl,
            trough_upnl=float(ladder.get("trough_upnl_pct") or upnl),
            bounce_pct=float(ladder.get("bounce_from_trough_pct") or 0),
            sig_dir=sig_dir,
            direction=direction,
            sig_conf=sig_conf,
            v_dir=v_dir,
            v_conf=v_conf,
            ladder=ladder,
        )
        if not rec:
            return GuardDecision(
                symbol, source, direction, "close", "medium",
                f"stale_flat_verdict — {stale_why} ({hold_sec:.0f}s)",
                upnl, v_conf, trade_action, checks, time.time(),
            )
        checks["recovery_defer"] = rec_why

    try:
        from risk_limits import get_active_limits
        reverse_conf = get_active_limits().min_signal_confidence
    except Exception:
        reverse_conf = 0.57
    if (
        sig_dir in ("long", "short")
        and sig_dir != direction
        and (signal or {}).get("is_valid")
        and conf_meets(sig_conf, reverse_conf)
    ):
        return GuardDecision(
            symbol, source, direction, "close", "high",
            f"Sinyal ters yön ({sig_dir.upper()} {sig_conf:.0%}) — pozisyon kapat",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    action = "hold"
    urgency = "low"
    reason = f"İzleniyor — AI güven {v_conf:.0%}, PnL {upnl:+.2f}%"
    if ladder.get("recovery_armed"):
        reason = (
            f"Toparlanma modu — dip {float(ladder.get('trough_upnl_pct') or 0):+.2f}% "
            f"→ hedef +{LOSS_TO_PROFIT_TARGET_PCT:.2f}% (şimdi {upnl:+.2f}%)"
        )
        urgency = "medium"

    if upnl > peak_upnl:
        peak_upnl = upnl
        checks["peak_upnl_pct"] = round(peak_upnl, 3)

    breakeven_armed = bool(ladder.get("breakeven_armed"))
    if peak_upnl >= BREAKEVEN_ACTIVATE_PCT:
        breakeven_armed = True
        checks["breakeven_armed"] = True
    if breakeven_armed and upnl <= BREAKEVEN_FLOOR_PCT and hold_sec >= 120:
        rec, _ = recovery_should_hold(
            hold_sec=hold_sec, upnl=upnl, peak_upnl=peak_upnl,
            trough_upnl=float(ladder.get("trough_upnl_pct") or upnl),
            bounce_pct=float(ladder.get("bounce_from_trough_pct") or 0),
            sig_dir=sig_dir, direction=direction, sig_conf=sig_conf,
            v_dir=v_dir, v_conf=v_conf, ladder=ladder,
        )
        if not rec:
            return GuardDecision(
                symbol, source, direction, "close", "high",
                f"Breakeven stop — zirve {peak_upnl:+.2f}% → {upnl:+.2f}%",
                upnl, v_conf, trade_action, checks, time.time(),
            )

    tp_pct = float(ladder.get("take_profit_pct") or TAKE_PROFIT_PCT)
    if upnl >= tp_pct:
        return GuardDecision(
            symbol, source, direction, "close", "high",
            f"Kâr hedefi %{tp_pct:.2f} — kademeli çıkış (PnL {upnl:+.2f}%)",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    for tier in sorted(_profit_tiers(), reverse=True):
        if upnl >= tier:
            return GuardDecision(
                symbol, source, direction, "close", "high",
                f"Kâr kademesi %{tier:g} — realize (PnL {upnl:+.2f}%, zirve {peak_upnl:+.2f}%)",
                upnl, v_conf, trade_action, checks, time.time(),
            )

    if peak_upnl >= TRAIL_MIN_PEAK_PCT and upnl > PROFIT_PROTECT_PCT:
        giveback = peak_upnl - upnl
        if giveback >= TRAIL_GIVEBACK_PCT:
            return GuardDecision(
                symbol, source, direction, "close", "high",
                f"Trailing stop — zirve {peak_upnl:+.2f}% → {upnl:+.2f}% (geri {giveback:.2f}%)",
                upnl, v_conf, trade_action, checks, time.time(),
            )

    if upnl > PROFIT_PROTECT_PCT and sig_dir in ("long", "short") and sig_dir != direction and sig_conf >= 0.30:
        return GuardDecision(
            symbol, source, direction, "close", "high",
            f"Sat sinyali + kârda ({upnl:+.2f}%) — {sig_dir.upper()} {sig_conf:.0%}",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    if upnl > 0.15 and sig_dir in ("long", "short") and sig_dir != direction and sig_conf >= 0.35:
        return GuardDecision(
            symbol, source, direction, "close", "high",
            f"Sat sinyali + kârda ({upnl:+.2f}%) — {sig_dir.upper()} {sig_conf:.0%}",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    try:
        from risk_limits import get_active_limits
        flat_close_conf = get_active_limits().min_signal_confidence * 0.92
    except Exception:
        flat_close_conf = 0.55
    flat_exit = trade_action == "close" or (
        sig_dir == "flat" and v_dir == "flat" and v_conf >= flat_close_conf
    )
    if flat_exit:
        if upnl > PROFIT_PROTECT_PCT:
            pass
        elif paper_mode and hold_sec < PAPER_MIN_HOLD_SEC and upnl > -EMERGENCY_LOSS_PCT:
            pass
        elif upnl < 0:
            rec, rec_why = recovery_should_hold(
                hold_sec=hold_sec, upnl=upnl, peak_upnl=peak_upnl,
                trough_upnl=float(ladder.get("trough_upnl_pct") or upnl),
                bounce_pct=float(ladder.get("bounce_from_trough_pct") or 0),
                sig_dir=sig_dir, direction=direction, sig_conf=sig_conf,
                v_dir=v_dir, v_conf=v_conf, ladder=ladder,
            )
            if rec:
                reason = f"AI FLAT ertelendi — {rec_why}"
                urgency = "medium"
            elif peak_upnl >= TRAIL_MIN_PEAK_PCT and upnl > 0:
                return GuardDecision(
                    symbol, source, direction, "close", "high",
                    f"Kâr koruma — zirve {peak_upnl:+.2f}%, çıkış {upnl:+.2f}% (AI FLAT)",
                    upnl, v_conf, trade_action, checks, time.time(),
                )
            else:
                return GuardDecision(
                    symbol, source, direction, "close", "high",
                    "AI çıkış (FLAT) — toparlanma yok",
                    upnl, v_conf, trade_action, checks, time.time(),
                )
        elif peak_upnl >= TRAIL_MIN_PEAK_PCT and upnl > 0:
            return GuardDecision(
                symbol, source, direction, "close", "high",
                f"Kâr koruma — zirve {peak_upnl:+.2f}%, çıkış {upnl:+.2f}% (AI FLAT)",
                upnl, v_conf, trade_action, checks, time.time(),
            )
        else:
            return GuardDecision(
                symbol, source, direction, "close", "high",
                "AI çıkış (FLAT) — sinyal ve verdict uyumlu",
                upnl, v_conf, trade_action, checks, time.time(),
            )

    if v_dir == "flat" and direction in ("long", "short"):
        if upnl > PROFIT_PROTECT_PCT:
            return GuardDecision(
                symbol, source, direction, "close", "high",
                f"Kârda sat — AI FLAT ama PnL {upnl:+.2f}% (zirve {peak_upnl:+.2f}%)",
                upnl, v_conf, trade_action, checks, time.time(),
            )
        if paper_mode and v_conf < 0.55:
            pass
        elif paper_mode and hold_sec < PAPER_MIN_HOLD_SEC:
            pass
        elif upnl < 0:
            rec, rec_why = recovery_should_hold(
                hold_sec=hold_sec, upnl=upnl, peak_upnl=peak_upnl,
                trough_upnl=float(ladder.get("trough_upnl_pct") or upnl),
                bounce_pct=float(ladder.get("bounce_from_trough_pct") or 0),
                sig_dir=sig_dir, direction=direction, sig_conf=sig_conf,
                v_dir=v_dir, v_conf=v_conf, ladder=ladder,
            )
            if rec:
                reason = f"AI FLAT zararda ertelendi — {rec_why}"
                urgency = "medium"
            elif peak_upnl >= TRAIL_MIN_PEAK_PCT and upnl > 0:
                return GuardDecision(
                    symbol, source, direction, "close", "high",
                    f"Kâr koruma — zirve {peak_upnl:+.2f}% (AI FLAT, hâlâ +{upnl:+.2f}%)",
                    upnl, v_conf, trade_action, checks, time.time(),
                )
            else:
                return GuardDecision(
                    symbol, source, direction, "close", "high",
                    f"AI FLAT ({v_conf:.0%}) — toparlanma yok, kapat",
                    upnl, v_conf, trade_action, checks, time.time(),
                )
        elif peak_upnl >= TRAIL_MIN_PEAK_PCT and upnl > 0:
            return GuardDecision(
                symbol, source, direction, "close", "high",
                f"Kâr koruma — zirve {peak_upnl:+.2f}% (AI FLAT, hâlâ +{upnl:.2f}%)",
                upnl, v_conf, trade_action, checks, time.time(),
            )
        else:
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
        rec, rec_why = recovery_should_hold(
            hold_sec=hold_sec, upnl=upnl, peak_upnl=peak_upnl,
            trough_upnl=float(ladder.get("trough_upnl_pct") or upnl),
            bounce_pct=float(ladder.get("bounce_from_trough_pct") or 0),
            sig_dir=sig_dir, direction=direction, sig_conf=sig_conf,
            v_dir=v_dir, v_conf=v_conf, ladder=ladder,
        )
        if not rec:
            return GuardDecision(
                symbol, source, direction, "close", "high",
                f"Koruyucu zarar kes %{MAX_LOSS_PCT} ({upnl:.2f}%)",
                upnl, v_conf, trade_action, checks, time.time(),
            )
        reason = f"Zarar kes ertelendi — {rec_why}"
        urgency = "medium"

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


async def _record_position_tick(
    redis: aioredis.Redis,
    symbol: str,
    pos: dict,
    features: dict,
    signal: dict | None,
    dec: GuardDecision,
) -> dict | None:
    """Grafik beyni — blueprint / canlı / sürekli analiz / konsensüs + Ollama."""
    try:
        from position_plan import (
            build_entry_blueprint,
            build_forecast_curve,
            chart_consensus,
            mismatch_score,
            planned_price_now,
            rolling_analysis,
        )
    except ImportError:
        return None

    entry = float(pos.get("entry_price") or 0)
    entry_ts = float(pos.get("entry_time") or 0)
    direction = str(pos.get("direction") or "long")
    price = float(features.get("close") or features.get("last_price") or 0)
    if price <= 0 or entry <= 0:
        return None

    blueprint = pos.get("entry_blueprint") or pos.get("trade_plan") or {}
    if not blueprint and pos.get("entry_signal"):
        try:
            blueprint = build_entry_blueprint(entry, direction, pos["entry_signal"])
            pos["entry_blueprint"] = blueprint
            if not pos.get("trade_plan"):
                from position_plan import build_entry_plan
                pos["trade_plan"] = build_entry_plan(entry, direction, pos["entry_signal"])
            await redis.set(f"oms:position:{symbol}", json.dumps(pos), ex=86400)
        except Exception:
            blueprint = {}

    planned_p = planned_price_now(blueprint, entry_ts, direction, entry)
    forecast = build_forecast_curve(price, direction, signal)
    forecast_p = float(forecast[0]["price"]) if forecast else price
    mm = mismatch_score(price, planned_p, forecast_p, direction=direction)

    raw_ticks = await redis.lrange(f"oms:ticks:{symbol}", 0, 119)
    tick_history = []
    for r in raw_ticks:
        try:
            tick_history.append(json.loads(r))
        except json.JSONDecodeError:
            pass

    tick = {
        "ts_ms": int(time.time() * 1000),
        "ts": time.time(),
        "price": price,
        "upnl_pct": dec.unrealized_pct,
        "planned_price": planned_p,
        "blueprint_price": planned_p,
        "forecast_price": forecast_p,
        "mismatch": mm,
        "rsi": float(features.get("rsi_14") or 0),
        "volume_ratio": float(features.get("volume_ratio") or 1),
    }
    tick_history.insert(0, tick)

    rolling = rolling_analysis(tick_history, blueprint, entry, entry_ts, direction, signal)
    consensus = chart_consensus(rolling, dec.unrealized_pct, signal)

    why_move = _explain_price_move(direction, mm, rolling, features)
    brain = {
        "symbol": symbol,
        "updated_at": time.time(),
        "tick": tick,
        "mismatch": mm,
        "rolling": rolling,
        "consensus": consensus,
        "why_move": why_move,
        "blueprint_narrative": (blueprint.get("narrative") or "")[:400],
        "forecast": forecast[:12],
    }

    pipe = redis.pipeline()
    pipe.lpush(f"oms:ticks:{symbol}", json.dumps(tick))
    pipe.ltrim(f"oms:ticks:{symbol}", 0, 1199)
    pipe.set(f"oms:position:track:{symbol}", json.dumps({**tick, "severity": mm["severity"]}), ex=300)
    pipe.set(f"oms:chart:brain:{symbol}", json.dumps(brain), ex=120)
    await pipe.execute()

    publish_llm = mm["severity"] in ("warn", "critical") or consensus.get("action") in (
        "close", "take_partial", "tighten_stop",
    )
    if publish_llm:
        payload = {
            "symbol": symbol,
            "mismatch": mm,
            "tick": tick,
            "rolling": {"narrative": rolling.get("narrative"), "trend": rolling.get("trend")},
            "consensus": consensus,
            "blueprint": {
                "narrative": blueprint.get("narrative"),
                "reasons": blueprint.get("reasons"),
                "direction": direction,
            },
            "why_move": why_move,
        }
        await redis.publish("ch:position_track", json.dumps(payload, ensure_ascii=False))
        lesson = (
            f"[grafik] {why_move} | Konsensüs: {consensus.get('action')} "
            f"({', '.join(consensus.get('reasons') or [])})"
        )
        await redis.lpush(
            f"trade:lessons:{symbol}",
            json.dumps({"text": lesson, "ts": time.time(), "source": "chart_brain"}),
        )
        await redis.ltrim(f"trade:lessons:{symbol}", 0, 49)

    return brain


def _explain_price_move(
    direction: str,
    mm: dict,
    rolling: dict,
    features: dict,
) -> str:
    """Neden düşüyor/çıkıyor — LLM ve dashboard için kısa açıklama."""
    parts = [rolling.get("trend") or mm.get("why", "")]
    vs = float(mm.get("vs_planned") or 0)
    if direction == "long":
        if vs < -0.3:
            parts.append("fiyat planın altında — long baskı altında")
        elif vs > 0.3:
            parts.append("fiyat planın üstünde — long lehine")
    else:
        if vs > 0.3:
            parts.append("fiyat planın üstünde — short baskı altında")
        elif vs < -0.3:
            parts.append("fiyat planın altında — short lehine")
    rsi = float(features.get("rsi_14") or 50)
    if rsi > 68:
        parts.append(f"RSI aşırı alım {rsi:.0f}")
    elif rsi < 32:
        parts.append(f"RSI aşırı satım {rsi:.0f}")
    vol = float(features.get("volume_ratio") or 1)
    if vol > 1.5:
        parts.append(f"hacim artışı x{vol:.1f}")
    elif vol < 0.7:
        parts.append("düşük hacim — zayıf hareket")
    return " · ".join(p for p in parts if p)[:320]


async def _scan_position_keys(redis: aioredis.Redis, pattern: str) -> list[str]:
    keys: list[str] = []
    cursor = 0
    while True:
        cursor, batch = await redis.scan(cursor, match=pattern, count=100)
        keys.extend(k.decode() if isinstance(k, bytes) else k for k in batch)
        if cursor == 0:
            break
    return keys


async def list_open_positions(redis: aioredis.Redis) -> list[dict]:
    """OMS + shadow — portfolio cache expire olsa bile guard her ikisini görür."""
    positions: list[dict] = []

    for key in await _scan_position_keys(redis, "oms:position:*"):
        sym = key.split(":")[-1]
        pr = await redis.get(key)
        if not pr:
            continue
        try:
            p = json.loads(pr)
            p["symbol"] = sym
            p["source"] = "oms"
            positions.append(p)
        except json.JSONDecodeError:
            pass

    for key in await _scan_position_keys(redis, "shadow:positions:*"):
        parts = key.split(":")
        if len(parts) < 4:
            continue
        shadow_id, sym = parts[2], parts[3]
        pr = await redis.get(key)
        if not pr:
            continue
        try:
            p = json.loads(pr)
            positions.append({
                "symbol": sym,
                "direction": p.get("direction", "long"),
                "size_usd": float(p.get("size_usd", 0)),
                "entry_price": float(p.get("price", p.get("entry_price", 0))),
                "entry_time": p.get("time", p.get("entry_time")),
                "source": "shadow",
                "shadow_id": shadow_id,
                "ladder": p.get("ladder") or {},
            })
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

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
            if float(features.get("close") or 0) <= 0:
                try:
                    from price_resolver import price_from_features_raw
                    features["close"] = price_from_features_raw(res[0])
                except ImportError:
                    pass
        except json.JSONDecodeError:
            continue

        pos["source"] = pos.get("source", "oms")
        dec = evaluate_position(symbol, pos, features, context, signal, verdict, learn)

        if pos.get("source") == "oms":
            brain = await _record_position_tick(redis, symbol, pos, features, signal, dec)
            if brain:
                consensus = brain.get("consensus") or {}
                c_action = consensus.get("action")
                c_urgency = consensus.get("urgency", "low")
                if c_action in ("close", "take_partial", "tighten_stop") and c_urgency in (
                    "critical", "high", "medium",
                ):
                    if dec.action == "hold":
                        if c_action == "close" and dec.unrealized_pct < -0.2:
                            dec = GuardDecision(
                                symbol, dec.source, dec.direction,
                                "close", c_urgency,
                                f"Grafik konsensüs (close): "
                                f"{'; '.join(consensus.get('reasons') or [])} | {dec.reason}",
                                dec.unrealized_pct, dec.ai_confidence, dec.trade_action,
                                {**(dec.checks or {}), "chart_brain": True},
                                time.time(), dec.shadow_id,
                            )
                        elif c_action == "take_partial" and dec.unrealized_pct >= 0.15:
                            dec = GuardDecision(
                                symbol, dec.source, dec.direction,
                                "close", "high",
                                f"Grafik konsensüs (kısmi sat): "
                                f"{'; '.join(consensus.get('reasons') or [])} | {dec.reason}",
                                dec.unrealized_pct, dec.ai_confidence, dec.trade_action,
                                {**(dec.checks or {}), "chart_brain": True, "partial": True},
                                time.time(), dec.shadow_id,
                            )
                        elif c_action == "tighten_stop" and dec.unrealized_pct < 0:
                            dec = GuardDecision(
                                symbol, dec.source, dec.direction,
                                "close" if dec.unrealized_pct < -0.5 else "hold",
                                c_urgency,
                                f"Grafik konsensüs (stop sıkı): "
                                f"{'; '.join(consensus.get('reasons') or [])} | {dec.reason}",
                                dec.unrealized_pct, dec.ai_confidence, dec.trade_action,
                                {**(dec.checks or {}), "chart_brain": True},
                                time.time(), dec.shadow_id,
                            )

        ladder = pos.get("ladder") or {}
        peak = float(ladder.get("peak_upnl_pct") or 0)
        if dec.unrealized_pct > peak or ladder.get("trough_upnl_pct") is None:
            ladder = update_ladder_tracking(ladder, dec.unrealized_pct, float(dec.checks.get("hold_sec") or 0))
            if dec.unrealized_pct >= BREAKEVEN_ACTIVATE_PCT:
                ladder["breakeven_armed"] = True
            pos["ladder"] = ladder
            try:
                if pos.get("source") == "oms":
                    await redis.set(
                        f"oms:position:{symbol}",
                        json.dumps(pos),
                        ex=86400,
                    )
                elif pos.get("source") == "shadow" and pos.get("shadow_id"):
                    sid = pos["shadow_id"]
                    pos_key = f"shadow:positions:{sid}:{symbol}"
                    raw = await redis.get(pos_key)
                    if raw:
                        sp = json.loads(raw)
                        sp["ladder"] = ladder
                        await redis.set(pos_key, json.dumps(sp), ex=86400)
            except Exception as e:
                log.debug("peak_upnl persist %s: %s", symbol, e)
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
            try:
                from profit_rules import cooldown_key
                ck = cooldown_key(symbol, dec.source)
            except ImportError:
                ck = f"trade:cooldown:{dec.source}:{symbol}"
            await redis.set(ck, str(now + SYMBOL_COOLDOWN_SEC), ex=SYMBOL_COOLDOWN_SEC + 60)
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
