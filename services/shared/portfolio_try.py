"""10.000 TL portföy — USD/TRY kuru ile USDT cinsinden üst limit."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request

logger = logging.getLogger(__name__)

_CACHE: dict[str, float] = {"rate": 0.0, "ts": 0.0}
CACHE_SEC = int(os.getenv("USDTRY_CACHE_SEC", "300"))


def portfolio_try_amount() -> float:
    try:
        return float(os.getenv("PORTFOLIO_TRY", "10000"))
    except ValueError:
        return 10000.0


def fetch_usd_try_rate() -> float:
    """USDT/TRY — Binance spot (1 USDT ≈ USD)."""
    now = time.time()
    if _CACHE["rate"] > 0 and now - _CACHE["ts"] < CACHE_SEC:
        return _CACHE["rate"]

    url = os.getenv(
        "USDTRY_URL",
        "https://api.binance.com/api/v3/ticker/price?symbol=USDTTRY",
    )
    try:
        with urllib.request.urlopen(url, timeout=12) as resp:
            data = json.loads(resp.read())
        rate = float(data.get("price", 0))
        if rate > 0:
            _CACHE["rate"] = rate
            _CACHE["ts"] = now
            return rate
    except Exception as e:
        logger.warning("USDTRY fetch failed: %s", e)

    fallback = float(os.getenv("USDTRY_FALLBACK", "34.5"))
    if _CACHE["rate"] > 0:
        return _CACHE["rate"]
    return fallback


def portfolio_value_usd() -> float:
    """Max trading capital in USD (from TRY budget)."""
    explicit = os.getenv("PORTFOLIO_VALUE", "").strip()
    if explicit and not os.getenv("PORTFOLIO_TRY"):
        try:
            return float(explicit)
        except ValueError:
            pass
    try_amt = portfolio_try_amount()
    rate = fetch_usd_try_rate()
    if rate <= 0:
        return float(os.getenv("PORTFOLIO_VALUE", "10000"))
    return round(try_amt / rate, 2)


def fee_rate_per_side() -> float:
    try:
        return float(os.getenv("TRADE_FEE_PCT_PER_SIDE", "0.001"))
    except ValueError:
        return 0.001  # %0.10 alım / %0.10 satım


def round_trip_fee_pct() -> float:
    return fee_rate_per_side() * 2


def compute_net_pnl(
    entry_price: float,
    exit_price: float,
    direction: str,
    size_usd: float,
) -> dict:
    """Gross + net PnL with per-side commission."""
    if entry_price <= 0 or size_usd <= 0:
        return {
            "gross_pnl_pct": 0.0,
            "net_pnl_pct": 0.0,
            "gross_pnl_usd": 0.0,
            "net_pnl_usd": 0.0,
            "fee_entry_usd": 0.0,
            "fee_exit_usd": 0.0,
            "fee_total_usd": 0.0,
            "fee_total_pct": 0.0,
        }
    side = fee_rate_per_side()
    if direction == "long":
        gross_pct = (exit_price - entry_price) / entry_price
    else:
        gross_pct = (entry_price - exit_price) / entry_price
    fee_entry = size_usd * side
    fee_exit = size_usd * side
    gross_usd = size_usd * gross_pct
    net_usd = gross_usd - fee_entry - fee_exit
    net_pct = gross_pct - (side * 2)
    return {
        "gross_pnl_pct": round(gross_pct, 6),
        "net_pnl_pct": round(net_pct, 6),
        "gross_pnl_usd": round(gross_usd, 4),
        "net_pnl_usd": round(net_usd, 4),
        "fee_entry_usd": round(fee_entry, 4),
        "fee_exit_usd": round(fee_exit, 4),
        "fee_total_usd": round(fee_entry + fee_exit, 4),
        "fee_total_pct": round(side * 2, 6),
    }
