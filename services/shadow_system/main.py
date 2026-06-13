import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from paper_trader import PaperTrader
from shadow_evaluator import ShadowEvaluator
from promotion_engine import PromotionEngine
from trade_store import schedule_save

try:
    from profit_rules import (
        SHADOW_HARD_STOP_PCT,
        SHADOW_MAX_OPEN,
        SHADOW_MIN_CONFIDENCE,
        SYMBOL_COOLDOWN_SEC,
        MAX_POSITION_HOLD_SEC,
        BREAKEVEN_ACTIVATE_PCT,
        BREAKEVEN_FLOOR_PCT,
        SLOT_ROTATE_MIN_CONF,
        STALE_VERDICT_HOLD_SEC,
        agent_entry_ok,
        build_history_record,
        cooldown_after_close,
        cooldown_key,
        entry_allowed,
        is_blacklisted,
        is_on_cooldown,
        paper_cooldown_sec,
        profit_tiers,
    )
    from price_resolver import resolve_market_price
except ImportError:
    SHADOW_MIN_CONFIDENCE = 0.60
    SHADOW_MAX_OPEN = 3
    SHADOW_HARD_STOP_PCT = 1.2
    SYMBOL_COOLDOWN_SEC = 900
    MAX_POSITION_HOLD_SEC = 3600
    STALE_VERDICT_HOLD_SEC = 1200
    BREAKEVEN_ACTIVATE_PCT = 0.35
    BREAKEVEN_FLOOR_PCT = 0.08
    SLOT_ROTATE_MIN_CONF = 0.68

    async def resolve_market_price(redis, symbol: str) -> float:
        return 0.0

    def agent_entry_ok(direction: str, verdict: dict | None) -> tuple[bool, str]:
        return True, "ok"

    def cooldown_after_close(pnl_pct: float, *, blacklisted: bool = False) -> int:
        return SYMBOL_COOLDOWN_SEC

    def build_history_record(payload: dict) -> dict:
        return payload

    def is_blacklisted(_symbol: str) -> bool:
        return False

    def paper_cooldown_sec() -> int:
        return 600

    def cooldown_key(symbol: str, source: str = "shadow") -> str:
        return f"trade:cooldown:{source}:{symbol.upper()}"

    def is_on_cooldown(until: float | None) -> bool:
        return bool(until and time.time() < float(until))

    def profit_tiers() -> list[float]:
        return [1.5, 3.0, 6.0, 12.0]

    def entry_allowed(confidence: float, *, stop_pct: float = 0, tp_pct: float = 0, min_conf: float | None = None):
        mc = min_conf or SHADOW_MIN_CONFIDENCE
        if confidence < mc:
            return False, f"confidence {confidence:.2f} < {mc:.2f}"
        return True, "ok"

EMERGENCY_CHANNEL = "ch:emergency:close_all"
GUARD_CHANNEL = "ch:position:guard"
HALT_KEY = "system:trading:halted"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
PORTFOLIO_VALUE = float(os.getenv("PORTFOLIO_VALUE", "10000"))
SYMBOL_REFRESH_INTERVAL = 300


async def discover_symbols(redis: aioredis.Redis) -> list[str]:
    keys = await redis.keys("features:latest:*")
    symbols = [
        (k.decode() if isinstance(k, bytes) else k).split(":")[-1]
        for k in keys
    ]
    return sorted(symbols) if symbols else ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


trader = PaperTrader(initial_capital=PORTFOLIO_VALUE)


async def _sync_shadow_capital(redis: aioredis.Redis) -> float:
    """Dashboard/Redis bakiyesi → shadow paper sermayesi."""
    global PORTFOLIO_VALUE, trader
    try:
        from portfolio_cap import load_cap_usd

        usd = await load_cap_usd(redis)
    except ImportError:
        raw = await redis.get("portfolio:try:v1")
        usd = 0.0
        if raw:
            try:
                data = json.loads(raw)
                usd = float(
                    data.get("usd_cap") or data.get("portfolio_usd") or data.get("usd_capital") or 0
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        if usd <= 0:
            usd = PORTFOLIO_VALUE
    if usd > 0:
        PORTFOLIO_VALUE = usd
        for sid in SHADOW_IDS:
            p = trader.portfolios.get(sid)
            if p and p.initial_capital != usd:
                ratio = usd / p.initial_capital if p.initial_capital else 1.0
                p.initial_capital = usd
                p.capital = p.capital * ratio
        return usd
    return PORTFOLIO_VALUE
SHADOW_IDS = ["SHADOW_A", "SHADOW_B", "SHADOW_C"]
# Tek sembol = tek paper pozisyon (dashboard mükerrer satır olmasın)
SHADOW_OPEN_IDS = [
    s.strip()
    for s in os.getenv("SHADOW_OPEN_IDS", "SHADOW_A").split(",")
    if s.strip()
] or ["SHADOW_A"]
SHADOW_ONE_PER_SYMBOL = os.getenv("SHADOW_ONE_PER_SYMBOL", "true").lower() in (
    "1",
    "true",
    "yes",
)


async def _is_halted(redis: aioredis.Redis) -> bool:
    raw = await redis.get(HALT_KEY)
    if not raw:
        return False
    try:
        return bool(json.loads(raw).get("halted"))
    except json.JSONDecodeError:
        return True


async def flatten_all_shadow_positions(redis: aioredis.Redis) -> int:
    closed = 0
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="shadow:positions:*", count=200)
        for key in keys:
            k = key.decode() if isinstance(key, bytes) else key
            parts = k.split(":")
            if len(parts) < 4:
                continue
            shadow_id, symbol = parts[2], parts[3]
            pos_raw = await redis.get(k)
            if not pos_raw:
                continue
            try:
                pos = json.loads(pos_raw)
            except json.JSONDecodeError:
                continue
            ticker_raw = await redis.get(f"binance:ticker:{symbol.lower()}")
            if not ticker_raw:
                await redis.delete(k)
                continue
            ticker = json.loads(ticker_raw)
            ticker_data = ticker.get("data", ticker)
            price = float(ticker_data.get("b", ticker_data.get("best_bid", 0)))
            if price <= 0:
                continue
            pos_direction = pos.get("direction", "long")
            close_side = "SELL" if pos_direction == "long" else "BUY_COVER"
            result = trader.execute(shadow_id, symbol, close_side, price, 0)
            await redis.delete(k)
            if result:
                closed += 1
                await _finalize_close(
                    redis,
                    {
                        "shadow_id": shadow_id,
                        "symbol": symbol,
                        "source": "emergency",
                        "closed_at": time.time(),
                        "close_reason": "emergency_flatten",
                        "exit_reason": "emergency_flatten",
                        **result,
                    },
                    pos=pos,
                )
        if cursor == 0:
            break
    return closed


async def guard_listener(redis: aioredis.Redis):
    """AI position guard — shadow pozisyonlarını kapat."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(GUARD_CHANNEL)
    log.info("shadow_system subscribed to AI position guard")
    async for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        try:
            dec = json.loads(msg["data"])
            if dec.get("source") != "shadow":
                continue
            if dec.get("action") not in ("close", "emergency_close"):
                continue
            symbol = dec.get("symbol")
            shadow_id = dec.get("shadow_id") or "SHADOW_A"
            for sid in SHADOW_IDS:
                key = f"shadow:positions:{sid}:{symbol}"
                pos_raw = await redis.get(key)
                if not pos_raw:
                    continue
                pos = json.loads(pos_raw)
                ticker_raw = await redis.get(f"binance:ticker:{symbol.lower()}")
                price = await resolve_market_price(redis, symbol)
                if price <= 0:
                    continue
                pos_direction = pos.get("direction", "long")
                close_side = "SELL" if pos_direction == "long" else "BUY_COVER"
                result = trader.execute(sid, symbol, close_side, price, 0)
                await redis.delete(key)
                if result:
                    await _finalize_close(
                        redis,
                        {
                            "shadow_id": sid,
                            "symbol": symbol,
                            "source": "guard",
                            "closed_at": time.time(),
                            "close_reason": str(dec.get("reason", ""))[:500],
                            "exit_reason": str(dec.get("reason", ""))[:500],
                            **result,
                        },
                        pos=pos,
                    )
                    log.warning(f"[GUARD→SHADOW] {sid} {symbol} closed")
                break
        except Exception as e:
            log.error(f"shadow guard_listener: {e}")


async def emergency_listener(redis: aioredis.Redis):
    pubsub = redis.pubsub()
    await pubsub.subscribe(EMERGENCY_CHANNEL)
    log.info("shadow_system subscribed to emergency close channel")
    async for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        try:
            n = await flatten_all_shadow_positions(redis)
            log.warning(f"EMERGENCY: flattened {n} shadow position(s)")
        except Exception as e:
            log.error(f"Shadow emergency error: {e}")


async def _shadow_owner(redis: aioredis.Redis, symbol: str) -> str | None:
    for sid in SHADOW_IDS:
        if await redis.exists(f"shadow:positions:{sid}:{symbol}"):
            return sid
    return None


async def dedupe_shadow_positions(redis: aioredis.Redis) -> int:
    """Aynı sembolde B/C kopyalarını sil — yalnızca leader shadow tutulur."""
    if not SHADOW_ONE_PER_SYMBOL:
        return 0
    leader = SHADOW_OPEN_IDS[0]
    by_symbol: dict[str, list[tuple[str, str]]] = {}
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="shadow:positions:*", count=200)
        for key in keys:
            k = key.decode() if isinstance(key, bytes) else key
            parts = k.split(":")
            if len(parts) < 4:
                continue
            sid, sym = parts[2], parts[3]
            by_symbol.setdefault(sym, []).append((sid, k))
        if cursor == 0:
            break
    removed = 0
    for sym, entries in by_symbol.items():
        if len(entries) <= 1:
            continue
        keep_sid = leader if any(e[0] == leader for e in entries) else entries[0][0]
        for sid, k in entries:
            if sid == keep_sid:
                continue
            await redis.delete(k)
            removed += 1
            log.info(f"shadow dedupe: removed duplicate {sid} {sym}")
    return removed


def _upnl_pct(direction: str, entry: float, price: float) -> float:
    if entry <= 0 or price <= 0:
        return 0.0
    if direction == "long":
        return (price - entry) / entry * 100
    return (entry - price) / entry * 100


async def _shadow_open_count(redis: aioredis.Redis, shadow_id: str) -> int:
    n = 0
    cursor = 0
    prefix = f"shadow:positions:{shadow_id}:"
    while True:
        cursor, keys = await redis.scan(cursor, match=f"{prefix}*", count=100)
        n += len(keys)
        if cursor == 0:
            break
    return n


async def _set_symbol_cooldown(redis: aioredis.Redis, symbol: str, *, pnl_pct: float = 0.0) -> None:
    sec = cooldown_after_close(pnl_pct, blacklisted=is_blacklisted(symbol))
    until = time.time() + sec
    await redis.set(cooldown_key(symbol, "shadow"), str(until), ex=sec + 120)


async def _is_symbol_cooled(redis: aioredis.Redis, symbol: str) -> bool:
    raw = await redis.get(cooldown_key(symbol, "shadow"))
    if not raw:
        return False
    try:
        return is_on_cooldown(float(raw))
    except (TypeError, ValueError):
        return False


async def _finalize_close(redis: aioredis.Redis, payload: dict, *, pos: dict | None = None) -> None:
    """Kapanış: trade history + pub/sub + postgres + cooldown."""
    reason = str(
        payload.get("exit_reason") or payload.get("close_reason") or payload.get("reason") or ""
    )[:500]
    payload["exit_reason"] = reason
    payload["close_reason"] = reason
    if pos:
        payload.setdefault("ladder", pos.get("ladder"))
        payload.setdefault("entry_signal", pos.get("entry_signal"))
        payload.setdefault("size_usd", pos.get("size_usd"))
    record = build_history_record(payload)
    sym = str(payload.get("symbol", ""))
    sid = payload.get("shadow_id", "SHADOW_A")
    await redis.lpush(f"shadow:trades:{sid}", json.dumps(payload))
    await redis.ltrim(f"shadow:trades:{sid}", 0, 999)
    await redis.lpush("oms:trade_history", json.dumps(record))
    await redis.ltrim("oms:trade_history", 0, 4999)
    await redis.publish("ch:trade_closed", json.dumps(record))
    schedule_save(record)
    if sym:
        pnl = float(payload.get("pnl_pct", 0) or 0)
        await _set_symbol_cooldown(redis, sym, pnl_pct=pnl)
    await _publish_portfolio(redis)


async def _publish_portfolio(redis: aioredis.Redis) -> None:
    try:
        from portfolio_sync import publish_portfolio_state
        await publish_portfolio_state(redis)
    except ImportError:
        pass


async def _force_close_shadow(
    redis: aioredis.Redis,
    shadow_id: str,
    symbol: str,
    pos: dict,
    price: float,
    reason: str,
) -> None:
    pos_key = f"shadow:positions:{shadow_id}:{symbol}"
    pos_direction = pos.get("direction", "long")
    close_side = "SELL" if pos_direction == "long" else "BUY_COVER"
    result = trader.execute(shadow_id, symbol, close_side, price, 0)
    await redis.delete(pos_key)
    if result:
        await _finalize_close(
            redis,
            {
                "shadow_id": shadow_id,
                "symbol": symbol,
                "source": "shadow_system",
                "close_reason": reason,
                "exit_reason": reason,
                "closed_at": time.time(),
                **result,
            },
            pos=pos,
        )
        log.warning(f"[SHADOW STOP] {shadow_id} {symbol} {reason} pnl={result.get('pnl_pct', 0):.2%}")


async def _persist_shadow_ladder(redis: aioredis.Redis, shadow_id: str, sym: str, ladder: dict) -> None:
    pos_key = f"shadow:positions:{shadow_id}:{sym}"
    raw = await redis.get(pos_key)
    if not raw:
        return
    try:
        pos = json.loads(raw)
        pos["ladder"] = ladder
        await redis.set(pos_key, json.dumps(pos), ex=86400)
    except json.JSONDecodeError:
        pass


async def _position_weakness_score(
    redis: aioredis.Redis,
    sym: str,
    pos: dict,
) -> float:
    price = await resolve_market_price(redis, sym)
    entry = float(pos.get("price", pos.get("entry_price", 0)))
    direction = str(pos.get("direction", "long"))
    upnl = _upnl_pct(direction, entry, price) if price > 0 else -5.0
    opened = float(pos.get("time", pos.get("entry_time", 0)) or 0)
    hold_sec = time.time() - opened if opened > 0 else 0
    entry_conf = float((pos.get("ladder") or {}).get("entry_confidence", 0.5))

    sig_raw = await redis.get(f"signal:latest:{sym}")
    sig_dir = "flat"
    if sig_raw:
        try:
            sig_dir = json.loads(sig_raw).get("direction", "flat")
        except json.JSONDecodeError:
            pass

    score = upnl
    if sig_dir == "flat":
        score -= 3.0
    elif sig_dir != direction:
        score -= 1.5
    if hold_sec >= STALE_VERDICT_HOLD_SEC:
        score -= 2.0
    score -= entry_conf * 0.5
    score -= hold_sec / 7200.0
    return score


async def _try_rotate_shadow_slot(
    redis: aioredis.Redis,
    shadow_id: str,
    symbol: str,
    confidence: float,
) -> bool:
    """3/3 doluyken zayıf pozisyonu kapat — yüksek conf sinyale yer aç."""
    if await _shadow_open_count(redis, shadow_id) < SHADOW_MAX_OPEN:
        return False
    if confidence < SLOT_ROTATE_MIN_CONF:
        return False

    weakest_sym: str | None = None
    weakest_pos: dict | None = None
    worst = float("inf")
    prefix = f"shadow:positions:{shadow_id}:"
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=f"{prefix}*", count=50)
        for key in keys:
            k = key.decode() if isinstance(key, bytes) else key
            sym = k.split(":")[-1]
            if sym == symbol:
                continue
            raw = await redis.get(k)
            if not raw:
                continue
            try:
                pos = json.loads(raw)
            except json.JSONDecodeError:
                continue
            sc = await _position_weakness_score(redis, sym, pos)
            if sc < worst:
                worst = sc
                weakest_sym = sym
                weakest_pos = pos
        if cursor == 0:
            break

    if not weakest_sym or not weakest_pos:
        return False
    w_conf = float((weakest_pos.get("ladder") or {}).get("entry_confidence", 0.5))
    if confidence < w_conf + 0.10:
        return False

    price = await resolve_market_price(redis, weakest_sym)
    if price <= 0:
        return False
    await _force_close_shadow(
        redis,
        shadow_id,
        weakest_sym,
        weakest_pos,
        price,
        f"slot_rotate → {symbol} conf={confidence:.0%}",
    )
    return True


async def _enforce_hard_stops(redis: aioredis.Redis) -> None:
    """Tick başı — açık shadow pozisyonlarında sert stop (guard beklemeden)."""
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="shadow:positions:*", count=100)
        for key in keys:
            k = key.decode() if isinstance(key, bytes) else key
            parts = k.split(":")
            if len(parts) < 4:
                continue
            shadow_id, sym = parts[2], parts[3]
            if shadow_id not in SHADOW_OPEN_IDS:
                continue
            pos_raw = await redis.get(k)
            if not pos_raw:
                continue
            try:
                pos = json.loads(pos_raw)
            except json.JSONDecodeError:
                continue
            entry = float(pos.get("price", pos.get("entry_price", 0)) or 0)
            direction = str(pos.get("direction", "long"))
            opened = float(pos.get("time", pos.get("entry_time", 0)) or 0)
            hold_sec = time.time() - opened if opened > 0 else 0

            price = await resolve_market_price(redis, sym)
            if price <= 0 and entry > 0:
                price = entry

            ladder = dict(pos.get("ladder") or {})
            upnl = _upnl_pct(direction, entry, price) if price > 0 and entry > 0 else 0.0
            sl_pct = float(ladder.get("stop_loss_pct") or SHADOW_HARD_STOP_PCT)
            tp_pct = float(ladder.get("take_profit_pct") or profit_tiers()[0])

            peak = float(ladder.get("peak_upnl_pct") or upnl)
            if upnl > peak:
                ladder["peak_upnl_pct"] = round(upnl, 4)
            if float(ladder.get("peak_upnl_pct") or 0) >= BREAKEVEN_ACTIVATE_PCT:
                ladder["breakeven_armed"] = True
            if ladder != pos.get("ladder"):
                await _persist_shadow_ladder(redis, shadow_id, sym, ladder)

            close_price = price if price > 0 else entry
            if close_price <= 0:
                continue

            if hold_sec >= MAX_POSITION_HOLD_SEC:
                await _force_close_shadow(
                    redis, shadow_id, sym, pos, close_price,
                    f"max_hold {MAX_POSITION_HOLD_SEC // 60}dk ({upnl:+.2f}%)",
                )
                continue

            if hold_sec >= STALE_VERDICT_HOLD_SEC:
                sig_raw = await redis.get(f"signal:latest:{sym}")
                sig_dir = "flat"
                if sig_raw:
                    try:
                        sig_dir = json.loads(sig_raw).get("direction", "flat")
                    except json.JSONDecodeError:
                        pass
                if sig_dir == "flat" or sig_dir != direction:
                    await _force_close_shadow(
                        redis, shadow_id, sym, pos, close_price,
                        f"stale_flat_verdict ({hold_sec:.0f}s, {upnl:+.2f}%)",
                    )
                    continue

            if price <= 0:
                continue

            if ladder.get("breakeven_armed") and upnl <= BREAKEVEN_FLOOR_PCT and hold_sec >= 120:
                await _force_close_shadow(
                    redis, shadow_id, sym, pos, price,
                    f"breakeven_stop zirve {peak:+.2f}% → {upnl:+.2f}%",
                )
            elif upnl <= -sl_pct:
                await _force_close_shadow(
                    redis, shadow_id, sym, pos, price,
                    f"hard_stop %{sl_pct:.1f} ({upnl:+.2f}%)",
                )
            elif upnl >= tp_pct:
                await _force_close_shadow(
                    redis, shadow_id, sym, pos, price,
                    f"take_profit %{tp_pct:.1f} ({upnl:+.2f}%)",
                )
        if cursor == 0:
            break


async def simulate_tick(redis: aioredis.Redis, symbol: str):
    if await _is_halted(redis):
        return
    if is_blacklisted(symbol):
        return
    if await _is_symbol_cooled(redis, symbol):
        return
    sig_raw = await redis.get(f"signal:latest:{symbol}")
    if not sig_raw:
        return
    signal = json.loads(sig_raw)
    direction = signal.get("direction")
    confidence = float(signal.get("confidence", 0.5))
    if direction == "flat" or not signal.get("is_valid"):
        return

    verdict_raw = await redis.get(f"agents:verdict:{symbol}")
    verdict = json.loads(verdict_raw) if verdict_raw else None
    ok_agent, agent_why = agent_entry_ok(direction, verdict)
    if not ok_agent:
        return

    ctx_raw = await redis.get(f"context:latest:{symbol}")
    if ctx_raw:
        try:
            ctx = json.loads(ctx_raw)
            if int(ctx.get("crisis_level", 0) or 0) >= 2 and confidence < 0.65:
                return
        except json.JSONDecodeError:
            pass

    price = await resolve_market_price(redis, symbol)
    if price <= 0:
        return

    decision = signal.get("decision") or {}
    sl_pct = float(decision.get("stop_loss_pct") or signal.get("stop_loss_pct") or 1.2)
    tp_tiers = decision.get("take_profit_tiers_pct") or signal.get("take_profit_tiers") or profit_tiers()
    tp_pct = float(tp_tiers[0] if tp_tiers else profit_tiers()[0])
    ok, why = entry_allowed(confidence, stop_pct=sl_pct, tp_pct=tp_pct)
    if not ok:
        return

    try:
        from risk_limits import get_active_limits
        lim = get_active_limits()
        max_pos_pct = lim.max_position_pct
        if max_pos_pct > 1:
            max_pos_pct = 0.05
        global_max_lev = float(lim.max_leverage)
    except Exception:
        max_pos_pct = 0.05
        global_max_lev = 3.0

    risk = signal.get("risk") or {}
    leverage = float(signal.get("leverage") or risk.get("recommended_leverage") or 1)
    leverage = max(1.0, min(leverage, global_max_lev))
    lev_reasons = signal.get("leverage_reasons") or risk.get("leverage_reasons") or []

    if risk.get("position_size_pct"):
        max_pos_pct = min(max_pos_pct, float(risk["position_size_pct"]))
    open_n = await _shadow_open_count(redis, SHADOW_OPEN_IDS[0])
    slot_budget = PORTFOLIO_VALUE / max(SHADOW_MAX_OPEN, 1)
    base_usd = min(PORTFOLIO_VALUE * max_pos_pct, slot_budget * 0.92)
    margin_usd = base_usd * min(confidence, 0.85)
    if open_n >= SHADOW_MAX_OPEN * 0.8:
        margin_usd *= 0.85
    if margin_usd <= 0:
        return
    port_pct = margin_usd / PORTFOLIO_VALUE if PORTFOLIO_VALUE > 0 else 0
    notional_usd = margin_usd * leverage
    owner = await _shadow_owner(redis, symbol) if SHADOW_ONE_PER_SYMBOL else None

    for shadow_id in SHADOW_IDS:
        pos_key = f"shadow:positions:{shadow_id}:{symbol}"
        pos_raw = await redis.get(pos_key)

        if pos_raw:
            pos = json.loads(pos_raw)
            if pos.get("direction") != direction:
                pos_direction = pos.get("direction", "long")
                close_side = "SELL" if pos_direction == "long" else "BUY_COVER"
                result = trader.execute(shadow_id, symbol, close_side, price, 0)
                if result:
                    await redis.delete(pos_key)
                    await _finalize_close(
                        redis,
                        {
                            "shadow_id": shadow_id,
                            "symbol": symbol,
                            "source": "shadow_system",
                            "closed_at": time.time(),
                            "close_reason": "signal_reverse",
                            "exit_reason": "signal_reverse",
                            **result,
                        },
                        pos=pos,
                    )
                    if SHADOW_ONE_PER_SYMBOL:
                        owner = None
            else:
                continue

    if SHADOW_ONE_PER_SYMBOL and owner:
        return

    open_targets = (
        SHADOW_OPEN_IDS
        if SHADOW_ONE_PER_SYMBOL
        else SHADOW_IDS
    )
    for shadow_id in open_targets:
        pos_key = f"shadow:positions:{shadow_id}:{symbol}"
        if await redis.exists(pos_key):
            continue
        if await _shadow_open_count(redis, shadow_id) >= SHADOW_MAX_OPEN:
            rotated = await _try_rotate_shadow_slot(redis, shadow_id, symbol, confidence)
            if not rotated or await _shadow_open_count(redis, shadow_id) >= SHADOW_MAX_OPEN:
                continue
        open_side = "BUY" if direction == "long" else "SELL_SHORT"
        result = trader.execute(shadow_id, symbol, open_side, price, margin_usd, leverage=leverage)
        if result:
            await redis.set(
                pos_key,
                json.dumps({
                    "direction": direction,
                    "price": price,
                    "size_usd": margin_usd,
                    "margin_usd": margin_usd,
                    "time": time.time(),
                    "entry_signal": signal,
                    "ladder": {
                        "take_profit_pct": tp_pct,
                        "stop_loss_pct": sl_pct,
                        "entry_confidence": confidence,
                        "leverage": leverage,
                        "leverage_reasons": lev_reasons[:6],
                        "position_size_pct": round(port_pct, 5),
                        "slot_budget_usd": round(slot_budget, 2),
                        "kelly_fraction": float(signal.get("kelly_fraction", 0) or 0),
                        "risk_reasons": (risk.get("reasons") or [])[:4],
                        "notional_usd": round(notional_usd, 2),
                    },
                }),
                ex=86400,
            )
            await _publish_portfolio(redis)
            log.info(
                f"[SHADOW OPEN] {shadow_id} {direction.upper()} {symbol} "
                f"conf={confidence:.2f} margin=${margin_usd:.0f} ({port_pct*100:.1f}%) "
                f"lev={leverage:.0f}x notional=${notional_usd:.0f} "
                f"sl={sl_pct}% tp={tp_pct}% reasons={','.join(lev_reasons[:3])}"
            )
            if SHADOW_ONE_PER_SYMBOL:
                break


async def report_loop(redis: aioredis.Redis):
    promo = PromotionEngine()
    while True:
        leaderboard = trader.leaderboard()
        await redis.set("shadow:leaderboard", json.dumps(leaderboard), ex=300)
        await redis.set("system:heartbeat:shadow_system", str(time.time()), ex=120)

        ready = [e for e in leaderboard if e.get("promotion_ready")]
        best = ready[0] if ready else (leaderboard[0] if leaderboard else None)
        approved = len(ready) > 0
        reason = "promotion criteria met" if approved else (
            f"best shadow {best['shadow_id']}: {best.get('checks', {})}" if best else "no shadow data"
        )
        if best and not approved:
            ok, reason = promo.should_promote(
                {
                    "total_trades": best.get("trades", 0),
                    "sharpe": best.get("sharpe", 0),
                    "win_rate": best.get("win_rate", 0),
                    "max_drawdown": best.get("metrics", {}).get("max_drawdown", 1),
                },
                PORTFOLIO_VALUE,
            )

        await redis.set(
            "system:promotion:status",
            json.dumps({
                "approved": approved,
                "reason": reason,
                "best_shadow_id": best["shadow_id"] if best else None,
                "ready_count": len(ready),
                "leaderboard": leaderboard,
                "updated_at": time.time(),
            }),
            ex=600,
        )

        for entry in ready:
            log.info(
                f"PROMOTION READY: {entry['shadow_id']} "
                f"Sharpe={entry['sharpe']:.2f} WR={entry['win_rate']:.1%}"
            )
        summary = ", ".join(f"{e['shadow_id']} S={e['sharpe']:.2f}" for e in leaderboard)
        log.info(f"Shadow leaderboard: [{summary}] promotion_approved={approved}")
        await asyncio.sleep(300)


async def capital_refresh_loop(redis: aioredis.Redis):
    while True:
        try:
            cap = await _sync_shadow_capital(redis)
            log.debug(f"shadow capital synced: ${cap:.2f}")
        except Exception as e:
            log.warning(f"shadow capital sync: {e}")
        await asyncio.sleep(30)


async def heartbeat_loop(redis: aioredis.Redis) -> None:
    while True:
        await redis.set("system:heartbeat:shadow_system", str(time.time()), ex=120)
        await asyncio.sleep(20)


async def main():
    log.info(
        f"shadow_system starting — open_ids={SHADOW_OPEN_IDS} "
        f"one_per_symbol={SHADOW_ONE_PER_SYMBOL}"
    )
    redis = await aioredis.from_url(REDIS_URL)
    await redis.set("system:heartbeat:shadow_system", str(time.time()), ex=120)
    await _sync_shadow_capital(redis)
    n = await dedupe_shadow_positions(redis)
    if n:
        log.warning(f"shadow dedupe: removed {n} duplicate position key(s)")
    redis_em = await aioredis.from_url(REDIS_URL)
    redis_guard = await aioredis.from_url(REDIS_URL)

    async def limits_refresh_loop():
        try:
            from risk_limits import bootstrap_limits
            await bootstrap_limits(redis)
            while True:
                await bootstrap_limits(redis)
                await asyncio.sleep(5)
        except ImportError:
            log.warning("risk_limits module missing — using defaults in simulate_tick")

    await asyncio.gather(
        heartbeat_loop(redis),
        _trading_loop(redis),
        report_loop(redis),
        emergency_listener(redis_em),
        guard_listener(redis_guard),
        limits_refresh_loop(),
        capital_refresh_loop(redis),
    )


async def _ordered_symbols(redis: aioredis.Redis, symbols: list[str]) -> list[str]:
    """Önce geçerli yüksek conf sinyaller — 12 ALIM_UYGUN önce işlensin."""
    hot: list[tuple[float, str]] = []
    for sym in symbols:
        raw = await redis.get(f"signal:latest:{sym}")
        if not raw:
            continue
        try:
            sig = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if sig.get("direction") in ("long", "short") and sig.get("is_valid"):
            hot.append((float(sig.get("confidence", 0)), sym))
    hot.sort(reverse=True)
    hot_syms = [s for _, s in hot]
    rest = [s for s in symbols if s not in hot_syms]
    return hot_syms + rest


async def _trading_loop(redis: aioredis.Redis):
    symbols: list[str] = []
    last_refresh = 0.0

    while True:
        now = time.time()
        if now - last_refresh > SYMBOL_REFRESH_INTERVAL or not symbols:
            symbols = await discover_symbols(redis)
            last_refresh = now
            log.info(f"shadow_system tracking {len(symbols)} symbols")
            await redis.set("system:heartbeat:shadow_system", str(time.time()), ex=120)

        try:
            await _enforce_hard_stops(redis)
        except Exception as e:
            log.error(f"shadow hard_stop: {e}")

        await _sync_shadow_capital(redis)

        ordered = await _ordered_symbols(redis, symbols)
        for symbol in ordered:
            try:
                await simulate_tick(redis, symbol)
            except Exception as e:
                log.error(f"Shadow tick error {symbol}: {e}")
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
