import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis

from promotion_gate import check_live_trading_allowed, DRY_RUN
from live_execution import execute_market_order
from trade_store import schedule_save
from emergency import EMERGENCY_CHANNEL, is_trading_halted
from portfolio_sync import publish_portfolio_state
from guard_listener import guard_listener

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
PORTFOLIO_VALUE = float(os.getenv("PORTFOLIO_VALUE", "10000"))
SYMBOL_REFRESH_INTERVAL = 300
RECOVERY_DCA_MAX_TIERS = int(os.getenv("RECOVERY_DCA_MAX_TIERS", "3"))
RECOVERY_MAX_SYMBOL_PCT = float(os.getenv("RECOVERY_MAX_SYMBOL_PCT", "0.15"))
_portfolio_usd = PORTFOLIO_VALUE


def _portfolio_cap() -> float:
    return _portfolio_usd


def _entry_reason_text(signal: dict) -> str:
    if signal.get("consensus_reasoning"):
        return str(signal["consensus_reasoning"])[:500]
    reasons = signal.get("decision_reasons") or []
    if reasons:
        return ", ".join(str(r) for r in reasons)[:500]
    det = (signal.get("ensemble") or {}).get("signal_detector") or {}
    det_reasons = det.get("reasons") or []
    if det_reasons:
        return ", ".join(str(r) for r in det_reasons)[:500]
    return str(signal.get("source", ""))[:500]


async def refresh_portfolio_cap(redis: aioredis.Redis) -> float:
    """Dashboard bakiyesi veya TRY→USD üst limit."""
    global _portfolio_usd
    try:
        from portfolio_cap import load_cap_usd, CAPITAL_KEY

        user_raw = await redis.get(CAPITAL_KEY)
        if user_raw:
            try:
                data = json.loads(user_raw)
                if data.get("source") == "dashboard":
                    v = float(data.get("usd_cap", 0) or 0)
                    if v > 0:
                        _portfolio_usd = v
                        return _portfolio_usd
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        _portfolio_usd = await load_cap_usd(redis)
        from portfolio_try import round_trip_fee_pct

        await redis.set(
            "portfolio:try:v1",
            json.dumps({
                "usd_cap": _portfolio_usd,
                "portfolio_usd": _portfolio_usd,
                "fee_round_trip_pct": round_trip_fee_pct(),
                "updated_at": time.time(),
                "source": "oms_refresh",
            }),
            ex=86400 * 7,
        )
    except Exception as e:
        log.warning(f"portfolio cap refresh: {e}")
    return _portfolio_usd


async def _total_open_exposure(redis: aioredis.Redis) -> float:
    total = 0.0
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="oms:position:*", count=100)
        for key in keys:
            raw = await redis.get(key)
            if not raw:
                continue
            try:
                total += float(json.loads(raw).get("size_usd", 0) or 0)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        if cursor == 0:
            break
    return total


def _unrealized_pct(pos: dict, price: float) -> float:
    entry = float(pos.get("entry_price", 0) or 0)
    if entry <= 0 or price <= 0:
        return 0.0
    direction = pos.get("direction", "long")
    if direction == "long":
        return (price - entry) / entry
    return (entry - price) / entry

# Running daily P&L (reset at UTC midnight)
_daily_pnl = 0.0
_last_reset_day = -1


async def discover_symbols(redis: aioredis.Redis) -> list[str]:
    """Discover tradeable symbols from live signal keys."""
    keys = await redis.keys("signal:latest:*")
    if keys:
        return sorted(
            (k.decode() if isinstance(k, bytes) else k).split(":")[-1]
            for k in keys
        )
    # Fallback to env var
    raw = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
    return [s.strip() for s in raw.split(",") if s.strip()]


async def request_immunity_approval(redis: aioredis.Redis, order_dict: dict) -> bool:
    """Send order to immunity system queue and wait for response."""
    request_id = str(uuid.uuid4())[:8]
    order_dict["request_id"] = request_id
    order_dict["portfolio_value"] = _portfolio_cap()
    order_dict["daily_pnl"] = _daily_pnl

    await redis.rpush("immunity:requests", json.dumps(order_dict))
    response_key = f"immunity:response:{request_id}"

    for _ in range(30):  # wait up to 3 seconds
        resp_raw = await redis.get(response_key)
        if resp_raw:
            resp = json.loads(resp_raw)
            await redis.delete(response_key)
            if not resp["approved"]:
                log.info(f"Order rejected by immunity: {resp['reason']}")
            return resp["approved"]
        await asyncio.sleep(0.1)
    log.warning("Immunity system did not respond — rejecting order")
    return False


async def close_position(
    redis: aioredis.Redis,
    symbol: str,
    pos: dict,
    current_price: float,
    exit_meta: dict | None = None,
):
    """Close an existing position and record P&L."""
    global _daily_pnl
    entry_price = pos.get("entry_price", current_price)
    direction = pos.get("direction", "long")
    size_usd = pos.get("size_usd", 0)

    if not DRY_RUN and size_usd > 0 and current_price > 0:
        live_ok, live_reason = await check_live_trading_allowed(redis)
        if not live_ok:
            log.warning(f"Live close blocked for {symbol}: {live_reason}")
            return
        close_result = await execute_market_order(
            symbol, direction, size_usd, current_price, opening=False,
        )
        if not close_result:
            log.error(f"Live close failed — keeping redis position for {symbol}")
            return

    if entry_price > 0 and size_usd > 0:
        from portfolio_try import compute_net_pnl

        pnl = compute_net_pnl(entry_price, current_price, direction, size_usd)
        pnl_pct = pnl["net_pnl_pct"]
        pnl_usdt = pnl["net_pnl_usd"]
        _daily_pnl += pnl_usdt
        await redis.set("oms:daily_pnl", str(round(_daily_pnl, 4)))
        meta = exit_meta or {}
        hold_s = time.time() - pos.get("entry_time", time.time())
        ladder = pos.get("ladder") or {}
        entry_reason = str(ladder.get("entry_reason") or "")[:500]
        trade = {
            "symbol": symbol, "direction": direction,
            "action": "close",
            "entry_price": entry_price, "exit_price": current_price,
            "pnl_pct": pnl_pct,
            "pnl_usdt": pnl_usdt,
            "gross_pnl_pct": pnl["gross_pnl_pct"],
            "gross_pnl_usd": pnl["gross_pnl_usd"],
            "fee_entry_usd": pnl["fee_entry_usd"],
            "fee_exit_usd": pnl["fee_exit_usd"],
            "fee_total_usd": pnl["fee_total_usd"],
            "fee_total_pct": pnl["fee_total_pct"],
            "size_usd": size_usd, "source": "oms",
            "timestamp": int(time.time() * 1000),
            "closed_at": time.time(),
            "hold_seconds": hold_s,
            "entry_signal": pos.get("entry_signal"),
            "ladder": ladder,
            "entry_reason": entry_reason,
            "exit_reason": str(meta.get("reason", meta.get("close_reason", "")))[:500],
            "exit_urgency": str(meta.get("urgency", "")),
            "exit_action": str(meta.get("action", "close")),
            "unrealized_pct_at_close": meta.get("unrealized_pct"),
            "peak_upnl_pct": ladder.get("peak_upnl_pct"),
            "dca_tier": ladder.get("tier", 1),
            "fills": pos.get("fills", []),
        }
        await redis.lpush("oms:trade_history", json.dumps(trade))
        await redis.ltrim("oms:trade_history", 0, 4999)
        await redis.publish("ch:trade_closed", json.dumps(trade))
        schedule_save(trade)
        log.info(f"Position CLOSED: {symbol} {direction} pnl={pnl_pct:.2%} (${pnl_usdt:+.2f})")

    await redis.delete(f"oms:position:{symbol}")
    try:
        from profit_rules import SYMBOL_COOLDOWN_SEC, cooldown_key
        await redis.set(
            cooldown_key(symbol, "oms"),
            str(time.time() + SYMBOL_COOLDOWN_SEC),
            ex=SYMBOL_COOLDOWN_SEC + 120,
        )
    except ImportError:
        pass
    await publish_portfolio_state(redis)


async def get_price(redis: aioredis.Redis, symbol: str) -> float:
    """Get current mid price for a symbol."""
    ticker_raw = await redis.get(f"binance:ticker:{symbol.lower()}")
    if not ticker_raw:
        return 0.0
    ticker = json.loads(ticker_raw)
    ticker_data = ticker.get("data", ticker)
    bid = float(ticker_data.get("b", 0))
    ask = float(ticker_data.get("a", bid))
    return (bid + ask) / 2 if bid > 0 and ask > 0 else bid or ask


async def flatten_all_positions(redis: aioredis.Redis) -> int:
    """Emergency: close every open OMS position at market."""
    closed = 0
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="oms:position:*", count=100)
        for key in keys:
            k = key.decode() if isinstance(key, bytes) else key
            symbol = k.split(":")[-1]
            pos_raw = await redis.get(k)
            if not pos_raw:
                continue
            try:
                pos = json.loads(pos_raw)
            except json.JSONDecodeError:
                continue
            price = await get_price(redis, symbol)
            if price > 0:
                await close_position(redis, symbol, pos, price)
                closed += 1
        if cursor == 0:
            break
    return closed


async def emergency_listener(redis: aioredis.Redis):
    pubsub = redis.pubsub()
    await pubsub.subscribe(EMERGENCY_CHANNEL)
    log.info("OMS subscribed to emergency close channel")
    async for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        try:
            n = await flatten_all_positions(redis)
            log.warning(f"EMERGENCY: flattened {n} OMS position(s)")
            await redis.lpush(
                "activity:feed",
                json.dumps({
                    "type": "emergency",
                    "msg": f"Acil durum: {n} OMS pozisyonu kapatıldı",
                    "time": time.time(),
                }),
            )
        except Exception as e:
            log.error(f"Emergency flatten error: {e}")


async def process_signal(redis: aioredis.Redis, symbol: str):
    global _last_reset_day, _daily_pnl

    try:
        from profit_rules import is_blacklisted
        if is_blacklisted(symbol):
            return
    except ImportError:
        pass

    halted, _reason = await is_trading_halted(redis)
    if halted:
        return

    # Daily reset
    day = int(time.time() // 86400)
    if day != _last_reset_day:
        _daily_pnl = 0.0
        _last_reset_day = day
        await redis.set("oms:daily_pnl", "0")

    sig_raw = await redis.get(f"signal:latest:{symbol}")
    if not sig_raw:
        return
    signal = json.loads(sig_raw)

    direction = signal.get("direction", "flat")
    trade_action = signal.get("trade_action", "")
    pos_raw = await redis.get(f"oms:position:{symbol}")

    # Flat / close signal → exit open position (fixes AI flat vs open position desync)
    if direction == "flat" or trade_action == "close":
        if pos_raw:
            pos = json.loads(pos_raw)
            price = await get_price(redis, symbol)
            if price > 0:
                log.info(f"[{symbol}] Closing position — signal={direction} action={trade_action}")
                await close_position(
                    redis, symbol, pos, price,
                    exit_meta={
                        "reason": signal.get("close_reason") or f"signal_{trade_action or direction}",
                        "action": "close",
                        "urgency": "medium",
                    },
                )
        return

    if not signal.get("is_valid"):
        return

    try:
        from profit_rules import OMS_MIN_CONFIDENCE, cooldown_key, is_on_cooldown
        conf = float(signal.get("confidence", 0))
        if conf < OMS_MIN_CONFIDENCE:
            return
        cd_raw = await redis.get(cooldown_key(symbol, "oms"))
        if cd_raw:
            try:
                if is_on_cooldown(float(cd_raw)):
                    return
            except (TypeError, ValueError):
                pass
    except ImportError:
        if float(signal.get("confidence", 0)) < 0.60:
            return

    cap = _portfolio_cap()
    price = await get_price(redis, symbol)

    # Aynı yönde açık pozisyon — zararda kademeli ekleme (DCA recovery)
    if pos_raw:
        pos = json.loads(pos_raw)
        if pos.get("direction") == direction and price > 0:
            upnl = _unrealized_pct(pos, price)
            ladder = pos.get("ladder") or {}
            tier = int(ladder.get("tier", 1) or 1)
            initial = float(ladder.get("initial_size_usd", pos.get("size_usd", 0)) or 0)
            sym_cap = cap * RECOVERY_MAX_SYMBOL_PCT
            if (
                tier < RECOVERY_DCA_MAX_TIERS
                and -0.08 < upnl < -0.003
                and signal.get("is_valid")
                and float(pos.get("size_usd", 0)) < sym_cap
            ):
                add_usd = min(initial * 0.35, sym_cap - float(pos.get("size_usd", 0)))
                conf_ok = float(signal.get("confidence", 0)) >= 0.55
                if add_usd >= 5.0 and conf_ok:
                    dca_order = {
                        "symbol": symbol,
                        "side": "BUY" if direction == "long" else "SELL",
                        "size_usd": add_usd,
                        "leverage": 1.0,
                        "confidence": float(signal.get("confidence", 0)),
                        "signal_source": "recovery_dca",
                        "crisis_level": signal.get("crisis_level", 0),
                        "drift_status": signal.get("drift_status", "STABLE"),
                    }
                    if not await request_immunity_approval(redis, dca_order):
                        log.info(f"[DCA] {symbol} rejected by immunity")
                        return
                    old_sz = float(pos["size_usd"])
                    old_ep = float(pos["entry_price"])
                    new_sz = old_sz + add_usd
                    new_ep = (old_ep * old_sz + price * add_usd) / new_sz
                    fills = list(pos.get("fills") or [])
                    fills.append({
                        "tier": tier + 1,
                        "price": price,
                        "size_usd": add_usd,
                        "reason": "recovery_dca",
                        "upnl_before": round(upnl * 100, 3),
                        "ts": time.time(),
                    })
                    ladder.update({
                        "tier": tier + 1,
                        "initial_size_usd": initial or old_sz,
                        "last_dca_reason": "Zararda kademeli alış — ortalama maliyet düşürme",
                    })
                    pos.update({
                        "size_usd": new_sz,
                        "entry_price": new_ep,
                        "fills": fills,
                        "ladder": ladder,
                    })
                    await redis.set(f"oms:position:{symbol}", json.dumps(pos), ex=86400)
                    log.info(
                        f"[DCA] {symbol} tier={tier + 1} +${add_usd:.0f} "
                        f"avg={new_ep:.4f} upnl={upnl:.2%}"
                    )
                    await publish_portfolio_state(redis)
            return
        if pos.get("direction") != direction and price > 0:
            await close_position(
                redis, symbol, pos, price,
                exit_meta={"reason": "signal_reverse", "action": "close"},
            )

    confidence = float(signal.get("confidence", 0))
    kelly = float(signal.get("kelly_fraction", 0.01))
    try:
        from risk_limits import get_active_limits, is_paper_unlimited
        lim = get_active_limits()
        max_pos_pct = min(lim.max_position_pct, RECOVERY_MAX_SYMBOL_PCT * 100) / 100.0
        if lim.max_position_pct > 1:
            max_pos_pct = RECOVERY_MAX_SYMBOL_PCT
        paper = is_paper_unlimited()
    except Exception:
        max_pos_pct = RECOVERY_MAX_SYMBOL_PCT
        paper = DRY_RUN

    open_exposure = await _total_open_exposure(redis)
    room = max(0.0, cap - open_exposure)
    size_usd = min(
        cap * kelly * confidence,
        cap * max_pos_pct,
        room,
    )
    if paper:
        size_usd = max(size_usd, cap * 0.003)

    min_notional = 5.0 if paper else 10.0
    if size_usd < min_notional:
        return

    leverage = float(signal.get("leverage") or (signal.get("risk") or {}).get("recommended_leverage") or 1)
    try:
        from risk_limits import get_active_limits
        leverage = max(1.0, min(leverage, get_active_limits().max_leverage))
    except Exception:
        leverage = max(1.0, min(leverage, 3.0))

    if price <= 0:
        price = await get_price(redis, symbol)
    if price <= 0:
        return

    order_request = {
        "symbol": symbol,
        "side": "BUY" if direction == "long" else "SELL",
        "size_usd": size_usd,
        "leverage": leverage,
        "confidence": confidence,
        "signal_source": signal.get("source", "signal_engine"),
        "crisis_level": signal.get("crisis_level", 0),
        "drift_status": signal.get("drift_status", "STABLE"),
    }

    approved = await request_immunity_approval(redis, order_request)
    if not approved:
        return

    live_ok, live_reason = await check_live_trading_allowed(redis)
    if not live_ok:
        log.warning(f"Order blocked (live gate): {symbol} — {live_reason}")
        await redis.set(
            "system:live_trading:blocked",
            json.dumps({"symbol": symbol, "reason": live_reason, "ts": time.time()}),
            ex=120,
        )
        return

    if DRY_RUN:
        log.info(f"[DRY_RUN] {symbol} {direction.upper()} size=${size_usd:.2f} @ {price:.4f}")
    else:
        log.info(f"[LIVE] Executing {symbol} {direction.upper()} size=${size_usd:.2f} @ {price:.4f}")
        live_result = await execute_market_order(
            symbol, direction, size_usd, price, opening=True, leverage=leverage,
        )
        if not live_result:
            log.error(f"[LIVE] Order failed — position not opened for {symbol}")
            return

    decision = signal.get("decision") or {}
    tp_tiers = (
        decision.get("take_profit_tiers_pct")
        or signal.get("take_profit_tiers")
        or []
    )
    tp_pct = float(tp_tiers[0] if tp_tiers else os.getenv("PAPER_TAKE_PROFIT_PCT", "1.5"))
    sl_pct = float(
        decision.get("stop_loss_pct")
        or signal.get("stop_loss_pct")
        or os.getenv("PAPER_STOP_LOSS_PCT", "1.2")
    )
    trade_plan: dict = {}
    entry_blueprint: dict = {}
    try:
        from position_plan import build_entry_blueprint, build_entry_plan

        entry_blueprint = build_entry_blueprint(price, direction, signal)
        trade_plan = build_entry_plan(price, direction, signal)
    except ImportError:
        pass
    entry_ts = time.time()
    # Track the paper/live position
    await redis.set(f"oms:position:{symbol}", json.dumps({
        "symbol": symbol, "direction": direction,
        "size_usd": size_usd, "entry_price": price,
        "entry_time": entry_ts, "entry_signal": signal,
        "entry_blueprint": entry_blueprint,
        "trade_plan": trade_plan,
        "ladder": {
            "tier": 1,
            "initial_size_usd": size_usd,
            "take_profit_pct": tp_pct,
            "stop_loss_pct": sl_pct,
            "entry_confidence": confidence,
            "entry_reason": _entry_reason_text(signal),
            "leverage": leverage,
            "leverage_reasons": (signal.get("leverage_reasons") or [])[:6],
            "notional_usd": round(size_usd * leverage, 2),
        },
        "fills": [{
            "tier": 1,
            "price": price,
            "size_usd": size_usd,
            "reason": "entry",
            "ts": time.time(),
        }],
    }), ex=86400)
    await publish_portfolio_state(redis)


async def snapshot_portfolio(redis: aioredis.Redis):
    """Write hourly equity snapshot for portfolio equity curve."""
    while True:
        try:
            trade_hist_raw = await redis.lrange("oms:trade_history", 0, 999)
            trades = []
            for r in trade_hist_raw:
                try:
                    trades.append(json.loads(r))
                except Exception:
                    pass
            trades.sort(key=lambda t: t.get("closed_at", 0))
            equity = _portfolio_cap()
            for t in trades:
                equity += t.get("pnl_usdt", 0)
            snapshot = {
                "ts": int(time.time()),
                "equity": round(equity, 2),
                "trade_count": len(trades),
            }
            await redis.lpush("portfolio:pnl:snapshots", json.dumps(snapshot))
            await redis.ltrim("portfolio:pnl:snapshots", 0, 719)  # 30 days × 24h
        except Exception as e:
            log.warning(f"Snapshot error: {e}")
        await asyncio.sleep(3600)  # hourly


async def heartbeat_loop(redis: aioredis.Redis) -> None:
    while True:
        await redis.set("system:heartbeat:oms", str(time.time()), ex=120)
        await asyncio.sleep(20)


async def main():
    mode = "DRY_RUN" if DRY_RUN else "LIVE"
    redis = await aioredis.from_url(REDIS_URL)
    await redis.set("system:heartbeat:oms", str(time.time()), ex=120)
    await refresh_portfolio_cap(redis)
    log.info(f"OMS starting — {mode} mode — portfolio=${_portfolio_cap():.2f} (TRY cap)")

    symbols: list[str] = []
    last_refresh = 0.0

    async def portfolio_sync_loop():
        while True:
            try:
                await publish_portfolio_state(redis)
                await redis.set("system:heartbeat:oms", str(time.time()), ex=120)
            except Exception as e:
                log.debug(f"portfolio sync: {e}")
            await asyncio.sleep(5)

    async def try_refresh_loop():
        while True:
            await refresh_portfolio_cap(redis)
            await asyncio.sleep(300)

    async def signal_loop():
        nonlocal symbols, last_refresh
        while True:
            now = time.time()
            if now - last_refresh > SYMBOL_REFRESH_INTERVAL or not symbols:
                symbols = await discover_symbols(redis)
                last_refresh = now
                log.info(f"OMS tracking {len(symbols)} symbols")

            for symbol in symbols:
                try:
                    await process_signal(redis, symbol)
                except Exception as e:
                    log.error(f"OMS error for {symbol}: {e}")
            await asyncio.sleep(5)

    async def apply_guard_close(redis_client: aioredis.Redis, symbol: str, pos: dict, dec: dict):
        price = await get_price(redis_client, symbol)
        if price > 0:
            await close_position(redis_client, symbol, pos, price, exit_meta=dec)
            await redis_client.lpush(
                "activity:feed",
                json.dumps({
                    "type": "guard_close",
                    "symbol": symbol,
                    "action": dec.get("action"),
                    "reason": dec.get("reason", "")[:200],
                    "upnl_pct": dec.get("unrealized_pct"),
                    "time": time.time(),
                }),
            )
            await redis_client.ltrim("activity:feed", 0, 499)

    redis_em = await aioredis.from_url(REDIS_URL)
    redis_guard = await aioredis.from_url(REDIS_URL)
    async def limits_refresh_loop():
        from risk_limits import bootstrap_limits
        await bootstrap_limits(redis)
        while True:
            await bootstrap_limits(redis)
            await asyncio.sleep(5)

    await asyncio.gather(
        heartbeat_loop(redis),
        signal_loop(),
        portfolio_sync_loop(),
        try_refresh_loop(),
        snapshot_portfolio(redis),
        emergency_listener(redis_em),
        guard_listener(redis_guard, apply_guard_close),
        limits_refresh_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())
