# IMMUTABLE — DO NOT MODIFY WITHOUT SECURITY REVIEW
# Every order must pass through ImmunitySystem.check_order() before execution.

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ══════ ABSOLUTE LIMITS — DO NOT CHANGE ══════
MAX_POSITION_PCT = 0.05        # max 5% of portfolio per trade — IMMUTABLE
MAX_DAILY_LOSS_PCT = 0.02      # max 2% daily drawdown → halt — IMMUTABLE
MAX_LEVERAGE = 3.0             # max leverage — IMMUTABLE
MIN_LIQUIDITY_USD = 1_000_000
MIN_CONFIDENCE = 0.52
FORBIDDEN_ASSETS: set[str] = set()

# ══════ TRAINING MODE LIMITS — configurable via env ══════
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "50"))

CRISIS_SCALE = {0: 1.00, 1: 0.65, 2: 0.35, 3: 0.10, 4: 0.00}
DRIFT_KELLY_PENALTY = {"STABLE": 0.50, "WARNING": 0.35, "DRIFTING": 0.20, "SHOCK": 0.00}

CRISIS_TRIGGERS = {
    "funding_rate_extreme": 0.003,
    "vix_high": 40,
    "vix_extreme": 60,
    "spread_extreme": 0.5,
}


@dataclass
class OrderRequest:
    symbol: str
    side: str           # BUY / SELL
    size_usd: float
    leverage: float
    confidence: float
    signal_source: str
    crisis_level: int
    drift_status: str


@dataclass
class OrderDecision:
    approved: bool
    size_usd: float
    reason: str


class ImmunitySystem:
    """Hard risk limits. Immutable. Called before every order."""

    def __init__(self):
        self._daily_loss = 0.0
        self._daily_trades = 0
        self._open_positions = 0
        self._system_halted = False
        self._halt_until = 0.0

    def check_order(self, order: dict, portfolio_value: float, daily_pnl: float) -> tuple[bool, str]:
        """Legacy dict-based interface kept for compatibility."""
        size_usd = float(order.get("size_usd", 0))
        leverage = float(order.get("leverage", 1.0))
        symbol = order.get("symbol", "")
        confidence = float(order.get("confidence", 0))
        crisis_level = int(order.get("crisis_level", 0))
        drift_status = order.get("drift_status", "STABLE")

        if symbol in FORBIDDEN_ASSETS:
            return False, f"asset {symbol} is forbidden"
        if leverage > MAX_LEVERAGE:
            return False, f"leverage {leverage} exceeds max {MAX_LEVERAGE}"
        if self._system_halted and time.time() < self._halt_until:
            return False, "system halted — daily loss limit reached"
        if confidence < MIN_CONFIDENCE:
            return False, f"confidence {confidence:.2f} below minimum {MIN_CONFIDENCE}"
        crisis_mult = CRISIS_SCALE.get(crisis_level, 0)
        if crisis_mult == 0:
            return False, f"crisis level {crisis_level}: trading prohibited"
        drift_mult = DRIFT_KELLY_PENALTY.get(drift_status, 0)
        if drift_mult == 0:
            return False, "SHOCK drift status: trading prohibited"
        if portfolio_value > 0 and size_usd / portfolio_value > MAX_POSITION_PCT:
            return False, f"position {size_usd/portfolio_value:.1%} exceeds {MAX_POSITION_PCT:.1%}"
        if portfolio_value > 0 and daily_pnl / portfolio_value < -MAX_DAILY_LOSS_PCT:
            self._system_halted = True
            self._halt_until = time.time() + 86400
            return False, "daily loss limit reached — halting until tomorrow"
        if self._daily_trades >= MAX_TRADES_PER_DAY:
            return False, "daily trade limit reached"
        if self._open_positions >= MAX_OPEN_POSITIONS:
            return False, f"max open positions ({MAX_OPEN_POSITIONS}) reached"
        return True, "ok"

    def evaluate(self, request: OrderRequest, portfolio_value: float,
                 win_rate: float, avg_win: float, avg_loss: float) -> OrderDecision:
        """Full evaluation with Kelly sizing."""
        order_dict = {
            "symbol": request.symbol, "size_usd": request.size_usd,
            "leverage": request.leverage, "confidence": request.confidence,
            "crisis_level": request.crisis_level, "drift_status": request.drift_status,
        }
        approved, reason = self.check_order(order_dict, portfolio_value, self._daily_loss * portfolio_value)
        if not approved:
            return OrderDecision(approved=False, size_usd=0, reason=reason)

        crisis_mult = CRISIS_SCALE.get(request.crisis_level, 0)
        drift_mult = DRIFT_KELLY_PENALTY.get(request.drift_status, 0.5)
        kelly_size = self._kelly(win_rate, avg_win, avg_loss) * drift_mult * crisis_mult
        final_size = min(kelly_size, MAX_POSITION_PCT) * portfolio_value
        return OrderDecision(approved=True, size_usd=final_size, reason="approved")

    def record_trade_result(self, pnl_pct: float, portfolio_value: float):
        self._daily_trades += 1
        if pnl_pct < 0:
            self._daily_loss += abs(pnl_pct)
        if self._daily_loss >= MAX_DAILY_LOSS_PCT:
            logger.critical(f"MAX DAILY LOSS REACHED: {self._daily_loss:.1%} — halting")
            self._system_halted = True
            self._halt_until = time.time() + 86400

    def reset_daily(self):
        self._daily_loss = 0.0
        self._daily_trades = 0
        if self._daily_loss < MAX_DAILY_LOSS_PCT * 0.5:
            self._system_halted = False

    def _kelly(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        if avg_loss <= 0:
            return 0.01
        b = avg_win / avg_loss
        q = 1 - win_rate
        kelly = (b * win_rate - q) / b
        return max(0.0, min(kelly, MAX_POSITION_PCT))
