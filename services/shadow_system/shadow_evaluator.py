import numpy as np

class ShadowEvaluator:
    def evaluate(self, trades: list[dict]) -> dict:
        if not trades:
            return {"sharpe": 0.0, "win_rate": 0.0, "total_trades": 0}
        pnls = [t["pnl"] for t in trades]
        arr = np.array(pnls)
        sharpe = arr.mean() / (arr.std() + 1e-9) * np.sqrt(252)
        win_rate = (arr > 0).mean()
        return {
            "sharpe": float(sharpe),
            "win_rate": float(win_rate),
            "total_trades": len(trades),
            "total_pnl": float(arr.sum()),
            "max_drawdown": float(self._max_drawdown(arr)),
        }

    def _max_drawdown(self, pnls: np.ndarray) -> float:
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = running_max - cumulative
        return float(drawdowns.max())
