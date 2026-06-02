import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis

from order_manager import OrderManager
from binance_executor import BinanceExecutor
from position_tracker import PositionTracker
from audit_logger import AuditLogger

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL          = os.getenv("REDIS_URL", "redis://redis:6379")
DRY_RUN            = os.getenv("DRY_RUN", "true").lower() == "true"
PORTFOLIO_VALUE    = float(os.getenv("PORTFOLIO_VALUE", "10000"))
MAX_POSITION_PCT   = float(os.getenv("MAX_POSITION_PCT", "0.05"))   # mirrors immunity
SYMBOL_REFRESH_INTERVAL   = 300
MIN_HOLD_SECONDS          = int(os.getenv("MIN_HOLD_SECONDS", "60"))
MAX_HOLD_MINUTES          = float(os.getenv("MAX_HOLD_MINUTES", "240"))
CONFIDENCE_EXIT_THRESHOLD = float(os.getenv("CONFIDENCE_EXIT_THRESHOLD", "0.45"))

# ── Stop-and-Reverse (SAR) ───────────────────────────────────────────────────
SAR_CONFIDENCE_THRESHOLD  = float(os.getenv("SAR_CONFIDENCE", "0.72"))
SAR_KELLY_DISCOUNT        = 0.80
SAR_MIN_LOSS_PCT          = -1.5
SAR_POSITION_MONITOR_INTERVAL = 5

# Running daily P&L (reset at UTC midnight)
_daily_pnl      = 0.0
_last_reset_day = -1


# ── Helpers ──────────────────────────────────────────────────────────────────

async def discover_symbols(redis: aioredis.Redis) -> list[str]:
    keys = await redis.keys("signal:latest:*")
    if keys:
        seen: set[str] = set()
        result: list[str] = []
        for k in keys:
            sym = (k.decode() if isinstance(k, bytes) else k).split(":")[-1].upper()
            if sym not in seen:
                seen.add(sym)
                result.append(sym)
        return sorted(result)
    raw = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


async def get_price(redis: aioredis.Redis, symbol: str) -> float:
    """Current mid-price. Falls back to features close if ticker missing."""
    ticker_raw = await redis.get(f"binance:ticker:{symbol.lower()}")
    if ticker_raw:
        td = json.loads(ticker_raw)
        d  = td.get("data", td)
        bid = float(d.get("b", 0))
        ask = float(d.get("a", bid))
        if bid > 0:
            return (bid + ask) / 2
    feat_raw = await redis.get(f"features:latest:{symbol}")
    if feat_raw:
        feat = json.loads(feat_raw)
        if feat.get("close", 0):
            return float(feat["close"])
    return 0.0


async def _load_ai_context(redis: aioredis.Redis, symbol: str) -> dict:
    """Load full AI context for a symbol — verdict, market ctx, lesson count."""
    verdict_raw, context_raw, lessons_len = await asyncio.gather(
        redis.get(f"agents:verdict:{symbol}"),
        redis.get(f"context:latest:{symbol}"),
        redis.llen("training:lessons"),
    )
    verdict = json.loads(verdict_raw) if verdict_raw else {}
    context = json.loads(context_raw) if context_raw else {}
    return {
        "agent_reasoning":        str(verdict.get("reasoning", ""))[:600],
        "agent_consensus":        float(verdict.get("consensus", 0)),
        "agent_direction":        str(verdict.get("direction", "flat")),
        "entry_regime":           str(context.get("regime", "unknown")),
        "entry_crisis_level":     int(context.get("crisis_level", 0)),
        "entry_vix":              float(context.get("vix_level", 0)),
        "entry_funding":          float(context.get("funding_rate", 0)),
        "training_lessons_count": int(lessons_len),
    }


async def request_immunity_approval(redis: aioredis.Redis, order_dict: dict) -> bool:
    request_id = str(uuid.uuid4())[:8]
    order_dict["request_id"]   = request_id
    order_dict["portfolio_value"] = PORTFOLIO_VALUE
    order_dict["daily_pnl"]    = _daily_pnl

    await redis.rpush("immunity:requests", json.dumps(order_dict))
    response_key = f"immunity:response:{request_id}"

    for _ in range(30):
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
    close_reason: str = "signal",
):
    """Close a position, record full AI-enriched trade data, publish to ch:trade_closed."""
    global _daily_pnl
    entry_price = pos.get("entry_price", current_price)
    direction   = pos.get("direction", "long")
    size_usd    = pos.get("size_usd", 0)
    trade_id    = pos.get("trade_id", str(uuid.uuid4())[:8])

    # Dedup guard
    dedup_key     = f"oms:trade_closed:{trade_id}"
    already_closed = await redis.get(dedup_key)
    if already_closed:
        log.warning(f"Duplicate close for {symbol} trade_id={trade_id} — skipping")
        await redis.delete(f"oms:position:{symbol}")
        return

    if entry_price > 0 and size_usd > 0:
        pnl_pct  = (
            (current_price - entry_price) / entry_price
            if direction == "long"
            else (entry_price - current_price) / entry_price
        )
        pnl_pct  -= 0.001   # 0.10% round-trip fee
        pnl_usdt  = size_usd * pnl_pct
        _daily_pnl += pnl_usdt
        await redis.set("oms:daily_pnl", str(round(_daily_pnl, 4)))

        hold_seconds = round(time.time() - float(pos.get("entry_time", time.time())), 1)
        entry_signal = pos.get("entry_signal", {})

        # Full AI-enriched trade record
        trade = {
            "trade_id":    trade_id,
            "symbol":      symbol,
            "direction":   direction,
            "entry_price": entry_price,
            "exit_price":  current_price,
            "entry_time":  pos.get("entry_time", 0),
            "closed_at":   time.time(),
            "pnl_pct":     round(pnl_pct, 6),
            "pnl_usdt":    round(pnl_usdt, 4),
            "size_usd":    size_usd,
            "source":      "oms",
            # Closure context
            "close_reason":    close_reason,
            "hold_seconds":    hold_seconds,
            # Signal context
            "confidence":      pos.get("confidence", float(entry_signal.get("confidence", 0))),
            "stop_pct":        pos.get("stop_pct",   entry_signal.get("stop_pct")),
            "tp_pct":          pos.get("tp_pct",     entry_signal.get("tp_pct")),
            "risk_reward":     entry_signal.get("risk_reward"),
            "regime":          entry_signal.get("regime", pos.get("entry_regime", "unknown")),
            "crisis_level":    pos.get("entry_crisis_level", entry_signal.get("crisis_level", 0)),
            "drift_status":    entry_signal.get("drift_status", "STABLE"),
            "ml_score":        entry_signal.get("ml_score"),
            # AI context
            "agent_reasoning":        pos.get("agent_reasoning", ""),
            "agent_consensus":        pos.get("agent_consensus", 0),
            "agent_direction":        pos.get("agent_direction", direction),
            "entry_regime":           pos.get("entry_regime", "unknown"),
            "entry_vix":              pos.get("entry_vix", 0),
            "entry_funding":          pos.get("entry_funding", 0),
            "training_lessons_count": pos.get("training_lessons_count", 0),
            "genome_id":              pos.get("genome_id"),
        }

        await redis.set(dedup_key, "1", ex=3600)
        await redis.lpush("oms:trade_history", json.dumps(trade))
        await redis.ltrim("oms:trade_history", 0, 999)
        await redis.publish("ch:trade_closed", json.dumps(trade))

        outcome = "WIN" if pnl_pct > 0 else "LOSS"
        log.info(
            f"[{outcome}] {symbol} {direction.upper()} closed via {close_reason} "
            f"pnl={pnl_pct:.2%} (${pnl_usdt:+.2f}) held={hold_seconds:.0f}s"
        )

    await redis.delete(f"oms:position:{symbol}")


async def process_signal(redis: aioredis.Redis, symbol: str):
    global _last_reset_day, _daily_pnl

    # Daily reset at UTC midnight
    day = int(time.time() // 86400)
    if day != _last_reset_day:
        _daily_pnl      = 0.0
        _last_reset_day = day
        await redis.set("oms:daily_pnl", "0")

    sig_raw = await redis.get(f"signal:latest:{symbol}")
    if not sig_raw:
        return
    signal = json.loads(sig_raw)

    if not signal.get("is_valid"):
        return

    direction = signal["direction"]
    pos_raw   = await redis.get(f"oms:position:{symbol}")

    if pos_raw:
        pos = json.loads(pos_raw)
        if pos.get("direction") == direction:
            return  # Already positioned correctly

        held_seconds = time.time() - pos.get("entry_time", time.time())
        if held_seconds < MIN_HOLD_SECONDS:
            return  # Minimum hold not yet elapsed

        price = await get_price(redis, symbol)
        if price > 0:
            await close_position(redis, symbol, pos, price, "signal_flip")

    if direction == "flat":
        return

    confidence = float(signal.get("confidence", 0))
    kelly      = float(signal.get("kelly_fraction", 0.01))
    size_usd   = min(
        PORTFOLIO_VALUE * kelly * confidence,
        PORTFOLIO_VALUE * MAX_POSITION_PCT,
    )

    if size_usd < 10:
        return

    price = await get_price(redis, symbol)
    if price <= 0:
        return

    order_request = {
        "symbol":        symbol,
        "side":          "BUY" if direction == "long" else "SELL",
        "size_usd":      size_usd,
        "leverage":      1.0,
        "confidence":    confidence,
        "signal_source": signal.get("source", "signal_engine"),
        "crisis_level":  signal.get("crisis_level", 0),
        "drift_status":  signal.get("drift_status", "STABLE"),
    }

    approved = await request_immunity_approval(redis, order_request)
    if not approved:
        # Faz 2: blok olayını yayınla → event_learner dersi üretir
        try:
            feat_raw = await redis.get(f"features:latest:{symbol}")
            regime   = json.loads(feat_raw).get("regime", "unknown") if feat_raw else "unknown"
            await redis.publish("ch:immunity_blocked", json.dumps({
                "symbol":     symbol,
                "side":       order_request["side"],
                "size_usd":   round(size_usd, 2),
                "confidence": confidence,
                "regime":     regime,
                "reason":     "immunity_check_failed",
                "ts":         time.time(),
            }))
        except Exception:
            pass
        return

    # Load full AI context before opening position
    ai_ctx = await _load_ai_context(redis, symbol)

    trade_id = str(uuid.uuid4())[:12]
    position_record = {
        "trade_id":   trade_id,
        "symbol":     symbol,
        "direction":  direction,
        "size_usd":   size_usd,
        "entry_price": price,
        "entry_time":  time.time(),
        "entry_signal": signal,
        # Flattened for quick access at close time
        "confidence": confidence,
        "stop_pct":   signal.get("stop_pct"),
        "tp_pct":     signal.get("tp_pct"),
        **ai_ctx,
    }
    await redis.set(f"oms:position:{symbol}", json.dumps(position_record), ex=86400)

    log.info(
        f"[{'DRY_RUN' if DRY_RUN else 'LIVE'}] OPEN {symbol} {direction.upper()} "
        f"${size_usd:.2f} @ {price:.4f} | conf={confidence:.1%} "
        f"regime={ai_ctx['entry_regime']} consensus={ai_ctx['agent_consensus']:.0%} "
        f"lessons={ai_ctx['training_lessons_count']}"
    )


async def maybe_reverse(
    redis: aioredis.Redis,
    symbol: str,
    closed_direction: str,
    current_price: float,
    loss_pct: float,
) -> bool:
    """Stop-and-Reverse: after a stop-loss, open in the opposite direction."""
    if loss_pct > SAR_MIN_LOSS_PCT:
        return False

    sig_raw = await redis.get(f"signal:latest:{symbol}")
    if not sig_raw:
        return False
    signal = json.loads(sig_raw)

    new_dir    = signal.get("direction", "flat")
    confidence = float(signal.get("confidence", 0))

    if new_dir == closed_direction or new_dir == "flat":
        return False
    if confidence < SAR_CONFIDENCE_THRESHOLD:
        return False

    kelly    = float(signal.get("kelly_fraction", 0.01))
    size_usd = min(
        PORTFOLIO_VALUE * kelly * confidence * SAR_KELLY_DISCOUNT,
        PORTFOLIO_VALUE * MAX_POSITION_PCT   * SAR_KELLY_DISCOUNT,
    )
    if size_usd < 10:
        return False

    order_request = {
        "symbol":        symbol,
        "side":          "BUY" if new_dir == "long" else "SELL",
        "size_usd":      size_usd,
        "leverage":      1.0,
        "confidence":    confidence,
        "signal_source": "stop_and_reverse",
        "is_reversal":   True,
        "crisis_level":  signal.get("crisis_level", 0),
        "drift_status":  signal.get("drift_status", "STABLE"),
    }

    approved = await request_immunity_approval(redis, order_request)
    if not approved:
        log.info(f"[SAR] {symbol}: immunity rejected reversal")
        return False

    ai_ctx   = await _load_ai_context(redis, symbol)
    trade_id = str(uuid.uuid4())[:12]
    await redis.set(f"oms:position:{symbol}", json.dumps({
        "trade_id":    trade_id,
        "symbol":      symbol,
        "direction":   new_dir,
        "size_usd":    size_usd,
        "entry_price": current_price,
        "entry_time":  time.time(),
        "entry_signal": signal,
        "confidence":  confidence,
        "stop_pct":    signal.get("stop_pct"),
        "tp_pct":      signal.get("tp_pct"),
        "is_reversal": True,
        **ai_ctx,
    }), ex=86400)

    log.info(
        f"[SAR] {symbol}: {closed_direction.upper()} → {new_dir.upper()} "
        f"@ {current_price:.5f} | loss={loss_pct:+.2f}% | conf={confidence:.1%}"
    )

    sar_event = {
        "symbol":    symbol,
        "from_dir":  closed_direction,
        "to_dir":    new_dir,
        "price":     current_price,
        "loss_pct":  round(loss_pct, 4),
        "confidence": round(confidence, 4),
        "size_usd":  round(size_usd, 2),
        "timestamp": time.time(),
    }
    await redis.lpush("oms:sar_trades", json.dumps(sar_event))
    await redis.ltrim("oms:sar_trades", 0, 499)
    await redis.publish("ch:sar_triggered", json.dumps({
        "symbol": symbol, "from": closed_direction, "to": new_dir,
        "loss_pct": round(loss_pct, 4), "ts": time.time(),
    }))
    return True


async def position_monitor(redis: aioredis.Redis):
    """Every 5s: manage open positions — stop/TP/signal-flip/confidence/max-hold."""
    while True:
        await asyncio.sleep(SAR_POSITION_MONITOR_INTERVAL)
        pos_keys = await redis.keys("oms:position:*")
        for k in pos_keys:
            pos_raw = await redis.get(k)
            if not pos_raw:
                continue
            try:
                pos         = json.loads(pos_raw)
                symbol      = pos.get("symbol", "")
                direction   = pos.get("direction", "long")
                entry_price = float(pos.get("entry_price", 0))
                if not symbol or entry_price <= 0:
                    continue

                entry_signal = pos.get("entry_signal", {})
                stop_pct     = float(pos.get("stop_pct") or entry_signal.get("stop_pct") or 0)
                tp_pct       = float(pos.get("tp_pct")   or entry_signal.get("tp_pct")   or 0)

                # ATR-based default stops if signal didn't provide them
                if not stop_pct or not tp_pct:
                    feat_raw = await redis.get(f"features:latest:{symbol}")
                    if feat_raw:
                        feats = json.loads(feat_raw)
                        atr_v = float(feats.get("atr_pct", 0) or 0) * 100
                        if atr_v > 0:
                            if not stop_pct:
                                stop_pct = -atr_v * 1.5 if direction == "long" else atr_v * 1.5
                            if not tp_pct:
                                tp_pct   =  atr_v * 2.5 if direction == "long" else -atr_v * 2.5

                current_price = await get_price(redis, symbol)
                if current_price <= 0:
                    continue

                chg          = (current_price - entry_price) / entry_price * 100
                held_minutes = (time.time() - float(pos.get("entry_time", time.time()))) / 60

                # ── 0. Time-based force-close ─────────────────────────────────
                if held_minutes >= MAX_HOLD_MINUTES:
                    log.info(f"MAX_HOLD: {symbol} {direction} {held_minutes:.0f}dk pnl={chg:+.2f}%")
                    await close_position(redis, symbol, pos, current_price, "max_hold")
                    continue

                # ── 1. Stop-loss ──────────────────────────────────────────────
                hit_stop = (
                    (direction == "long"  and stop_pct and chg <= stop_pct) or
                    (direction == "short" and stop_pct and chg >= stop_pct)
                )
                # ── 2. Take-profit ────────────────────────────────────────────
                hit_tp = (
                    (direction == "long"  and tp_pct and chg >= tp_pct) or
                    (direction == "short" and tp_pct and chg <= tp_pct)
                )

                if hit_stop:
                    log.info(f"STOP_LOSS: {symbol} {direction} chg={chg:+.2f}%")
                    await close_position(redis, symbol, pos, current_price, "stop_loss")
                    await maybe_reverse(redis, symbol, direction, current_price, chg)

                elif hit_tp:
                    log.info(f"TAKE_PROFIT: {symbol} {direction} chg={chg:+.2f}%")
                    await close_position(redis, symbol, pos, current_price, "take_profit")

                else:
                    sig_raw = await redis.get(f"signal:latest:{symbol}")
                    if sig_raw:
                        new_sig  = json.loads(sig_raw)
                        new_dir  = new_sig.get("direction", direction)
                        new_conf = float(new_sig.get("confidence", 1.0))

                        # AI signal flipped direction
                        if new_dir not in (direction, "flat") and chg >= (stop_pct * 0.8 if stop_pct else -2.0):
                            log.info(f"SIGNAL_FLIP: {symbol} {direction}→{new_dir} chg={chg:+.2f}%")
                            await close_position(redis, symbol, pos, current_price, "signal_flip")
                            await maybe_reverse(redis, symbol, direction, current_price, chg)

                        # Confidence collapsed — take profit if in green
                        elif new_conf < CONFIDENCE_EXIT_THRESHOLD and chg > -0.5:
                            log.info(f"CONF_EXIT: {symbol} conf={new_conf:.2%} chg={chg:+.2f}%")
                            await close_position(redis, symbol, pos, current_price, "confidence_exit")

            except Exception as e:
                log.error(f"Position monitor error: {e}")


async def snapshot_portfolio(redis: aioredis.Redis):
    """Hourly equity snapshots for the portfolio curve."""
    while True:
        try:
            raws   = await redis.lrange("oms:trade_history", 0, 999)
            trades = []
            for r in raws:
                try:
                    trades.append(json.loads(r))
                except Exception:
                    pass
            trades.sort(key=lambda t: t.get("closed_at", 0))
            equity = PORTFOLIO_VALUE
            for t in trades:
                equity += t.get("pnl_usdt", 0)
            snapshot = {
                "ts":           int(time.time()),
                "equity":       round(equity, 2),
                "trade_count":  len(trades),
            }
            await redis.lpush("portfolio:pnl:snapshots", json.dumps(snapshot))
            await redis.ltrim("portfolio:pnl:snapshots", 0, 719)  # 30 days × 24h
        except Exception as e:
            log.warning(f"Snapshot error: {e}")
        await asyncio.sleep(3600)


async def cleanup_duplicate_positions(redis: aioredis.Redis):
    """Startup cleanup: normalise position keys to uppercase, remove duplicates."""
    keys = await redis.keys("oms:position:*")
    seen: dict[str, str] = {}
    for k in keys:
        raw_key = k.decode() if isinstance(k, bytes) else k
        sym     = raw_key.split(":")[-1].upper()
        if sym in seen:
            try:
                existing_raw = await redis.get(seen[sym])
                current_raw  = await redis.get(raw_key)
                existing     = json.loads(existing_raw) if existing_raw else {}
                current      = json.loads(current_raw)  if current_raw  else {}
                if current.get("entry_time", 0) > existing.get("entry_time", 0):
                    await redis.delete(seen[sym])
                    seen[sym] = raw_key
                else:
                    await redis.delete(raw_key)
                log.info(f"Cleanup: removed duplicate position key for {sym}")
            except Exception as e:
                log.warning(f"Cleanup error for {sym}: {e}")
        else:
            seen[sym] = raw_key
            if raw_key != f"oms:position:{sym}":
                val = await redis.get(raw_key)
                if val:
                    await redis.set(f"oms:position:{sym}", val, ex=86400)
                    await redis.delete(raw_key)
                    log.info(f"Cleanup: renamed {raw_key} → oms:position:{sym}")


async def main():
    mode = "DRY_RUN" if DRY_RUN else "LIVE"
    log.info(
        f"OMS starting — {mode} | portfolio=${PORTFOLIO_VALUE:.0f} "
        f"| max_position={MAX_POSITION_PCT:.0%}"
    )
    redis = await aioredis.from_url(REDIS_URL)
    await cleanup_duplicate_positions(redis)

    symbols:      list[str] = []
    last_refresh: float     = 0.0

    async def signal_loop():
        nonlocal symbols, last_refresh
        while True:
            now = time.time()
            if now - last_refresh > SYMBOL_REFRESH_INTERVAL or not symbols:
                symbols      = await discover_symbols(redis)
                last_refresh = now
                log.info(f"OMS tracking {len(symbols)} symbols")

            for symbol in symbols:
                try:
                    await process_signal(redis, symbol)
                except Exception as e:
                    log.error(f"OMS error for {symbol}: {e}")
            await asyncio.sleep(5)

    await asyncio.gather(signal_loop(), snapshot_portfolio(redis), position_monitor(redis))


if __name__ == "__main__":
    asyncio.run(main())
