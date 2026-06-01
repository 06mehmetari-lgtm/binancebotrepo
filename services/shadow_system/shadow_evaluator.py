import numpy as np


class ShadowEvaluator:
    """
    Evaluates shadow trading performance from a list of closed trades.
    Sharpe uses per-trade returns annualised by assuming ~252 trades/year
    (roughly daily trading frequency — more conservative than using sqrt(252)
    which would imply daily return data).
    """

    def evaluate(self, trades: list[dict]) -> dict:
        if not trades:
            return {"sharpe": 0.0, "win_rate": 0.0, "total_trades": 0,
                    "total_pnl": 0.0, "max_drawdown": 0.0}

        pnls = np.array([float(t.get("pnl", t.get("pnl_pct", 0))) for t in trades])

        # Sharpe: use sample std (ddof=1), annualise with sqrt(trades_per_year)
        # Using 252 as conventional annual trade count is reasonable
        std = float(np.std(pnls, ddof=1)) if len(pnls) > 1 else 1e-9
        sharpe = float(np.mean(pnls) / max(std, 1e-9) * np.sqrt(252))

        win_rate = float(np.mean(pnls > 0))
        max_dd = self._max_drawdown(pnls)

        return {
            "sharpe":       round(sharpe, 4),
            "win_rate":     round(win_rate, 4),
            "total_trades": len(trades),
            "total_pnl":    round(float(np.sum(pnls)), 6),
            "max_drawdown": round(max_dd, 4),
        }

    def _max_drawdown(self, pnls: np.ndarray) -> float:
        """Maximum peak-to-trough drawdown of the cumulative P&L curve."""
        if len(pnls) == 0:
            return 0.0
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        # Relative drawdown from peak (avoid div-by-zero with small offset)
        rel_dd = (running_max - cumulative) / np.maximum(np.abs(running_max), 1e-6)
        return float(np.max(rel_dd))
