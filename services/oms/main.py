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

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
PORTFOLIO_VALUE = float(os.getenv("PORTFOLIO_VALUE", "10000"))
SYMBOL_REFRESH_INTERVAL = 300
MIN_HOLD_SECONDS = int(os.getenv("MIN_HOLD_SECONDS", "60"))   # 60s minimum pozisyon süresi (hızlı al-sat)
MAX_HOLD_MINUTES = float(os.getenv("MAX_HOLD_MINUTES", "240"))  # 4 saat sonra zorla kapat
CONFIDENCE_EXIT_THRESHOLD = float(os.getenv("CONFIDENCE_EXIT_THRESHOLD", "0.45"))

# ── Stop-and-Reverse (SAR) parametreleri ────────────────────────────────────
# Stop-loss vurduğunda karşı yönde pozisyon açmak için eşikler.
# Immunity sistemi limitleri (MAX_LEVERAGE, MAX_POSITION_PCT vb.) yine de geçerlidir.
SAR_CONFIDENCE_THRESHOLD = float(os.getenv("SAR_CONFIDENCE", "0.72"))  # Giriş 0.60'tan yüksek
SAR_KELLY_DISCOUNT = 0.80          # Ters pozisyon %20 daha küçük (ihtiyat payı)
SAR_MIN_LOSS_PCT = -1.5            # En az -%1.5 zararda ise SAR değerlendirilir
SAR_POSITION_MONITOR_INTERVAL = 5  # Aktif pozisyonları kaç saniyede kontrol et

# Running daily P&L (reset at UTC midnight)
_daily_pnl = 0.0
_last_reset_day = -1


async def discover_symbols(redis: aioredis.Redis) -> list[str]:
    """Discover tradeable symbols from live signal keys."""
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
    # Fallback to env var
    raw = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


async def request_immunity_approval(redis: aioredis.Redis, order_dict: dict) -> bool:
    """Send order to immunity system queue and wait for response."""
    request_id = str(uuid.uuid4())[:8]
    order_dict["request_id"] = request_id
    order_dict["portfolio_value"] = PORTFOLIO_VALUE
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


async def close_position(redis: aioredis.Redis, symbol: str, pos: dict, current_price: float):
    """Close an existing position and record P&L."""
    global _daily_pnl
    entry_price = pos.get("entry_price", current_price)
    direction = pos.get("direction", "long")
    size_usd = pos.get("size_usd", 0)
    trade_id = pos.get("trade_id", str(uuid.uuid4())[:8])

    # Mükerrer kayıt önleme: aynı trade_id daha önce kaydedildiyse atla
    dedup_key = f"oms:trade_closed:{trade_id}"
    already_closed = await redis.get(dedup_key)
    if already_closed:
        log.warning(f"Duplicate close attempt for {symbol} trade_id={trade_id} — skipping")
        await redis.delete(f"oms:position:{symbol}")
        return

    if entry_price > 0 and size_usd > 0:
        if direction == "long":
            pnl_pct = (current_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_price) / entry_price
        pnl_pct -= 0.001  # 0.10% round-trip fee
        pnl_usdt = size_usd * pnl_pct
        _daily_pnl += pnl_usdt
        await redis.set("oms:daily_pnl", str(round(_daily_pnl, 4)))
        trade = {
            "trade_id": trade_id,
            "symbol": symbol, "direction": direction,
            "entry_price": entry_price, "exit_price": current_price,
            "entry_time": pos.get("entry_time", 0),
            "pnl_pct": round(pnl_pct, 6), "pnl_usdt": round(pnl_usdt, 4),
            "size_usd": size_usd, "source": "oms",
            "closed_at": time.time(),
        }
        await redis.set(dedup_key, "1", ex=3600)  # 1 saat dedup penceresi
        await redis.lpush("oms:trade_history", json.dumps(trade))
        await redis.ltrim("oms:trade_history", 0, 999)
        await redis.publish("ch:trade_closed", json.dumps(trade))
        log.info(f"Position CLOSED: {symbol} {direction} pnl={pnl_pct:.2%} (${pnl_usdt:+.2f})")

    await redis.delete(f"oms:position:{symbol}")


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


async def process_signal(redis: aioredis.Redis, symbol: str):
    global _last_reset_day, _daily_pnl

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

    if not signal.get("is_valid"):
        return

    direction = signal["direction"]
    pos_raw = await redis.get(f"oms:position:{symbol}")

    # If we have a position in the opposite direction, close it first
    if pos_raw:
        pos = json.loads(pos_raw)
        if pos.get("direction") == direction:
            return  # Already positioned correctly
        # Minimum hold süresi kontrolü — çok hızlı flip-flop önleme
        held_seconds = time.time() - pos.get("entry_time", time.time())
        if held_seconds < MIN_HOLD_SECONDS:
            return  # Henüz minimum süre dolmadı
        # Close opposite position
        price = await get_price(redis, symbol)
        if price > 0:
            await close_position(redis, symbol, pos, price)

    if direction == "flat":
        return

    confidence = float(signal.get("confidence", 0))
    kelly = float(signal.get("kelly_fraction", 0.01))
    size_usd = min(PORTFOLIO_VALUE * kelly * confidence, PORTFOLIO_VALUE * 0.05)

    if size_usd < 10:
        return

    price = await get_price(redis, symbol)
    if price <= 0:
        return

    order_request = {
        "symbol": symbol,
        "side": "BUY" if direction == "long" else "SELL",
        "size_usd": size_usd,
        "leverage": 1.0,
        "confidence": confidence,
        "signal_source": signal.get("source", "signal_engine"),
        "crisis_level": signal.get("crisis_level", 0),
        "drift_status": signal.get("drift_status", "STABLE"),
    }

    approved = await request_immunity_approval(redis, order_request)
    if not approved:
        return

    if DRY_RUN:
        log.info(f"[DRY_RUN] {symbol} {direction.upper()} size=${size_usd:.2f} @ {price:.4f}")
    else:
        log.info(f"[LIVE] Executing {symbol} {direction.upper()} size=${size_usd:.2f} @ {price:.4f}")

    # Track the paper/live position
    trade_id = str(uuid.uuid4())[:12]
    await redis.set(f"oms:position:{symbol}", json.dumps({
        "trade_id": trade_id,
        "symbol": symbol, "direction": direction,
        "size_usd": size_usd, "entry_price": price,
        "entry_time": time.time(), "entry_signal": signal,
    }), ex=86400)


async def maybe_reverse(
    redis: aioredis.Redis,
    symbol: str,
    closed_direction: str,
    current_price: float,
    loss_pct: float,
) -> bool:
    """Stop-and-Reverse: stop-loss kapandıktan sonra ters yönde pozisyon aç.

    Koşullar (hepsi sağlanmalı):
      1. Zarar SAR_MIN_LOSS_PCT eşiğini geçmiş olmalı
      2. Yeni sinyal kapatılan yönün tersi olmalı
      3. Sinyal güveni >= SAR_CONFIDENCE_THRESHOLD
      4. Immunity sistemi onaylamalı
    """
    if loss_pct > SAR_MIN_LOSS_PCT:
        return False  # Yeterli zarar yok, SAR tetiklenmiyor

    sig_raw = await redis.get(f"signal:latest:{symbol}")
    if not sig_raw:
        return False
    signal = json.loads(sig_raw)

    new_dir = signal.get("direction", "flat")
    confidence = float(signal.get("confidence", 0))

    if new_dir == closed_direction or new_dir == "flat":
        return False
    if confidence < SAR_CONFIDENCE_THRESHOLD:
        log.debug(f"[SAR] {symbol}: sinyal güveni {confidence:.2%} < eşik {SAR_CONFIDENCE_THRESHOLD:.2%}")
        return False

    kelly = float(signal.get("kelly_fraction", 0.01))
    size_usd = min(
        PORTFOLIO_VALUE * kelly * confidence * SAR_KELLY_DISCOUNT,
        PORTFOLIO_VALUE * 0.05 * SAR_KELLY_DISCOUNT,
    )
    if size_usd < 10:
        return False

    order_request = {
        "symbol": symbol,
        "side": "BUY" if new_dir == "long" else "SELL",
        "size_usd": size_usd,
        "leverage": 1.0,
        "confidence": confidence,
        "signal_source": "stop_and_reverse",
        "is_reversal": True,
        "crisis_level": signal.get("crisis_level", 0),
    }

    approved = await request_immunity_approval(redis, order_request)
    if not approved:
        log.info(f"[SAR] {symbol}: immunity sistemi ters pozisyonu reddetti")
        return False

    trade_id = str(uuid.uuid4())[:12]
    await redis.set(f"oms:position:{symbol}", json.dumps({
        "trade_id": trade_id,
        "symbol": symbol,
        "direction": new_dir,
        "size_usd": size_usd,
        "entry_price": current_price,
        "entry_time": time.time(),
        "entry_signal": signal,
        "is_reversal": True,
    }), ex=86400)

    log.info(
        f"[SAR] {symbol}: {closed_direction.upper()} → {new_dir.upper()} "
        f"@ {current_price:.5f} | zarar: {loss_pct:+.2f}% | güven: {confidence:.1%}"
    )

    await redis.lpush("oms:sar_trades", json.dumps({
        "symbol": symbol,
        "from_dir": closed_direction,
        "to_dir": new_dir,
        "price": current_price,
        "loss_pct": round(loss_pct, 4),
        "confidence": round(confidence, 4),
        "size_usd": round(size_usd, 2),
        "timestamp": time.time(),
    }))
    await redis.ltrim("oms:sar_trades", 0, 499)
    await redis.publish("ch:sar_triggered", json.dumps({
        "symbol": symbol, "from": closed_direction, "to": new_dir,
        "loss_pct": round(loss_pct, 4), "ts": time.time(),
    }))
    return True


async def position_monitor(redis: aioredis.Redis):
    """Her 5s: aktif pozisyonları yönet — stop/TP/sinyal flip/güven çöküşü.

    Öncelik sırası:
      1. Stop-loss → kapat + SAR dene
      2. Take-profit → kapat (kârı realize et)
      3. AI sinyali yön değiştirdi → kapat + SAR dene
      4. Güven %45 altına düştü ve kârdayız → realize et

    Stop/TP sinyal tarafından gelmiyorsa ATR bazlı varsayılan hesaplanır.
    """
    while True:
        await asyncio.sleep(SAR_POSITION_MONITOR_INTERVAL)
        pos_keys = await redis.keys("oms:position:*")
        for k in pos_keys:
            pos_raw = await redis.get(k)
            if not pos_raw:
                continue
            try:
                pos = json.loads(pos_raw)
                symbol      = pos.get("symbol", "")
                direction   = pos.get("direction", "long")
                entry_price = float(pos.get("entry_price", 0))
                if not symbol or entry_price <= 0:
                    continue

                entry_signal = pos.get("entry_signal", {})
                stop_pct = float(entry_signal.get("stop_pct", 0) or 0)
                tp_pct   = float(entry_signal.get("tp_pct",   0) or 0)

                # Sinyalde stop/TP yoksa ATR bazlı varsayılan uygula
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

                chg = (current_price - entry_price) / entry_price * 100
                held_minutes = (time.time() - pos.get("entry_time", time.time())) / 60

                # ── 0. Zaman bazlı zorunlu çıkış ──
                if held_minutes >= MAX_HOLD_MINUTES:
                    log.info(f"MAX HOLD TIME: {symbol} {direction} {held_minutes:.0f}dk → kapatılıyor (pnl={chg:+.2f}%)")
                    await close_position(redis, symbol, pos, current_price)
                    continue

                # ── 1. Stop-loss ──
                hit_stop = (
                    (direction == "long"  and stop_pct and chg <= stop_pct) or
                    (direction == "short" and stop_pct and chg >= stop_pct)
                )
                # ── 2. Take-profit ──
                hit_tp = (
                    (direction == "long"  and tp_pct and chg >= tp_pct) or
                    (direction == "short" and tp_pct and chg <= tp_pct)
                )

                if hit_stop:
                    log.info(f"STOP-LOSS: {symbol} {direction} chg={chg:+.2f}%")
                    await close_position(redis, symbol, pos, current_price)
                    await maybe_reverse(redis, symbol, direction, current_price, chg)

                elif hit_tp:
                    log.info(f"TAKE-PROFIT: {symbol} {direction} chg={chg:+.2f}% +${chg/100*pos.get('size_usd',0):.2f}")
                    await close_position(redis, symbol, pos, current_price)

                else:
                    # ── 3 & 4. AI sinyal/güven bazlı çıkış ──
                    sig_raw = await redis.get(f"signal:latest:{symbol}")
                    if sig_raw:
                        new_sig  = json.loads(sig_raw)
                        new_dir  = new_sig.get("direction", direction)
                        new_conf = float(new_sig.get("confidence", 1.0))

                        # AI yön değiştirdi → stop sınırı içindeyse çık + SAR dene
                        if new_dir not in (direction, "flat") and chg >= (stop_pct * 0.8 if stop_pct else -2.0):
                            log.info(f"SIGNAL FLIP: {symbol} {direction}→{new_dir} chg={chg:+.2f}%")
                            await close_position(redis, symbol, pos, current_price)
                            await maybe_reverse(redis, symbol, direction, current_price, chg)

                        # Güven çöktü → kârda veya küçük zararda çık
                        elif new_conf < CONFIDENCE_EXIT_THRESHOLD and chg > -0.5:
                            log.info(f"CONFIDENCE EXIT: {symbol} conf={new_conf:.2%} chg={chg:+.2f}%")
                            await close_position(redis, symbol, pos, current_price)

            except Exception as e:
                log.error(f"Position monitor error: {e}")


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
            equity = PORTFOLIO_VALUE
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


async def cleanup_duplicate_positions(redis: aioredis.Redis):
    """Startup: Redis'teki lowercase/mükerrer pozisyon anahtarlarını temizle."""
    keys = await redis.keys("oms:position:*")
    seen: dict[str, str] = {}  # uppercase_symbol -> canonical_key
    for k in keys:
        raw_key = k.decode() if isinstance(k, bytes) else k
        sym = raw_key.split(":")[-1].upper()
        if sym in seen:
            # Mükerrer: hangisi daha eski olanı sil
            try:
                existing_raw = await redis.get(seen[sym])
                current_raw = await redis.get(raw_key)
                existing = json.loads(existing_raw) if existing_raw else {}
                current = json.loads(current_raw) if current_raw else {}
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
            # Lowercase key varsa uppercase'e taşı
            if raw_key != f"oms:position:{sym}":
                val = await redis.get(raw_key)
                if val:
                    await redis.set(f"oms:position:{sym}", val, ex=86400)
                    await redis.delete(raw_key)
                    log.info(f"Cleanup: renamed {raw_key} → oms:position:{sym}")


async def main():
    mode = "DRY_RUN" if DRY_RUN else "LIVE"
    log.info(f"OMS starting — {mode} mode — portfolio=${PORTFOLIO_VALUE:.0f}")
    redis = await aioredis.from_url(REDIS_URL)
    await cleanup_duplicate_positions(redis)

    symbols: list[str] = []
    last_refresh = 0.0

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

    await asyncio.gather(signal_loop(), snapshot_portfolio(redis), position_monitor(redis))


if __name__ == "__main__":
    asyncio.run(main())
