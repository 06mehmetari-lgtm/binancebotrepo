"""Binance USDM live order execution — only when DRY_RUN=false and promotion gate passes."""

from __future__ import annotations

import asyncio
import logging
import os

from audit_logger import AuditLogger
from binance_executor import BinanceExecutor

log = logging.getLogger(__name__)

_executor: BinanceExecutor | None = None
_audit = AuditLogger()
_init_attempted = False


def get_executor() -> BinanceExecutor | None:
    global _executor, _init_attempted
    if _executor is not None:
        return _executor
    if _init_attempted:
        return None
    _init_attempted = True
    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    secret = (os.getenv("BINANCE_API_SECRET") or os.getenv("BINANCE_SECRET") or "").strip()
    if not api_key or not secret:
        log.warning("BinanceExecutor: API keys missing — live orders disabled")
        return None
    try:
        _executor = BinanceExecutor()
        log.info("BinanceExecutor initialized (testnet=%s)", os.getenv("BINANCE_TESTNET", "true"))
        return _executor
    except Exception as e:
        log.error("BinanceExecutor init failed: %s", e)
        return None


def _ccxt_side(direction: str, opening: bool) -> str:
    d = direction.lower()
    if opening:
        return "buy" if d == "long" else "sell"
    return "sell" if d == "long" else "buy"


async def execute_market_order(
    symbol: str,
    direction: str,
    size_usd: float,
    price: float,
    *,
    opening: bool = True,
) -> dict | None:
    """Place USDT-M futures market order. amount = base asset quantity."""
    ex = get_executor()
    if not ex or price <= 0 or size_usd < 10:
        return None
    amount = round(size_usd / price, 8)
    if amount <= 0:
        return None
    side = _ccxt_side(direction, opening)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: ex.market_order(symbol, side, amount)
        )
        order_id = str(result.get("id", result.get("orderId", "unknown")))
        _audit.log_order(order_id, "market", {
            "symbol": symbol,
            "side": side,
            "direction": direction,
            "opening": opening,
            "amount": amount,
            "size_usd": size_usd,
            "price_hint": price,
            "status": result.get("status"),
        })
        log.info(
            "LIVE ORDER %s %s %s qty=%.6f (~$%.2f)",
            symbol, side.upper(), "OPEN" if opening else "CLOSE", amount, size_usd,
        )
        return result
    except Exception as e:
        log.error("Live order failed %s %s: %s", symbol, side, e)
        _audit.log_order("failed", "market_error", {
            "symbol": symbol, "side": side, "error": str(e),
        })
        return None
