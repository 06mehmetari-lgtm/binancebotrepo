PROMOTION_CRITERIA = {
    "min_trades": 100,
    "min_sharpe": 1.5,
    "min_win_rate": 0.52,
    "max_drawdown": 0.10,
}

class PromotionEngine:
    def should_promote(self, metrics: dict, portfolio_value: float) -> tuple[bool, str]:
        if metrics.get("total_trades", 0) < PROMOTION_CRITERIA["min_trades"]:
            return False, f"insufficient trades ({metrics.get('total_trades', 0)} < {PROMOTION_CRITERIA['min_trades']})"
        if metrics.get("sharpe", 0) < PROMOTION_CRITERIA["min_sharpe"]:
            return False, f"low Sharpe ({metrics.get('sharpe', 0):.2f})"
        if metrics.get("win_rate", 0) < PROMOTION_CRITERIA["min_win_rate"]:
            return False, f"low win rate ({metrics.get('win_rate', 0):.1%})"
        dd = metrics.get("max_drawdown", 0) / max(portfolio_value, 1)
        if dd > PROMOTION_CRITERIA["max_drawdown"]:
            return False, f"max drawdown {dd:.1%} too high"
        return True, "promotion criteria met"
