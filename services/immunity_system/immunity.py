# IMMUTABLE — DO NOT MODIFY WITHOUT SECURITY REVIEW

MAX_POSITION_PCT = 0.05        # max 5% of portfolio per trade
MAX_DAILY_LOSS_PCT = 0.02      # max 2% daily drawdown
MAX_OPEN_POSITIONS = 3
MAX_LEVERAGE = 3.0
MIN_LIQUIDITY_USD = 1_000_000
FORBIDDEN_ASSETS: set[str] = set()

class ImmunitySystem:
    def check_order(self, order: dict, portfolio_value: float, daily_pnl: float) -> tuple[bool, str]:
        size_usd = order.get("size_usd", 0)
        leverage = order.get("leverage", 1.0)
        symbol = order.get("symbol", "")

        if symbol in FORBIDDEN_ASSETS:
            return False, f"asset {symbol} is forbidden"

        if leverage > MAX_LEVERAGE:
            return False, f"leverage {leverage} exceeds max {MAX_LEVERAGE}"

        if portfolio_value > 0 and size_usd / portfolio_value > MAX_POSITION_PCT:
            return False, f"position size {size_usd/portfolio_value:.1%} exceeds {MAX_POSITION_PCT:.1%}"

        if portfolio_value > 0 and daily_pnl / portfolio_value < -MAX_DAILY_LOSS_PCT:
            return False, f"daily loss limit reached"

        return True, "ok"
