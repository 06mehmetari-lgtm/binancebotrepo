"""
Shadow (Paper) Trading System — 3 parallel universes.
Each shadow tracks its own portfolio. Promotion to live requires meeting performance criteria.
Supports both LONG and SHORT positions with correct P&L calculation.
"""

import json
import logging
import time
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

PROMOTION_CRITERIA = {
    "min_sharpe": 1.5,
    "min_win_rate": 0.52,
    "min_trades": 100,
    "max_drawdown": 0.10,
}


@dataclass
class ShadowPortfolio:
    shadow_id: str
    initial_capital: float
    capital: float = field(default=0.0)
    positions: dict = field(default_factory=dict)
    trades: list = field(default_factory=list)

    def __post_init__(self):
        if self.capital == 0.0:
            self.capital = self.initial_capital

    @property
    def total_value(self) -> float:
        return self.capital

    @property
    def total_return(self) -> float:
        return (self.total_value - self.initial_capital) / self.initial_capital

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t["pnl_pct"] > 0) / len(self.trades)

    @property
    def sharpe_ratio(self) -> float:
        if len(self.trades) < 5:
            return 0.0
        returns = [t["pnl_pct"] for t in self.trades]
        std = np.std(returns)
        if std == 0:
            return 0.0
        return float(np.mean(returns) / std * np.sqrt(252))

    @property
    def max_drawdown(self) -> float:
        if not self.trades:
            return 0.0
        cumulative = 1.0
        peak = 1.0
        max_dd = 0.0
        for t in self.trades:
            cumulative *= (1 + t["pnl_pct"])
            peak = max(peak, cumulative)
            dd = (peak - cumulative) / peak
            max_dd = max(max_dd, dd)
        return max_dd


class PaperTrader:
    def __init__(self, initial_capital: float = 10_000):
        self.portfolios: dict[str, ShadowPortfolio] = {
            sid: ShadowPortfolio(sid, initial_capital)
            for sid in ["SHADOW_A", "SHADOW_B", "SHADOW_C"]
        }

    def execute(
        self,
        shadow_id: str,
        symbol: str,
        side: str,
        price: float,
        size_usd: float,
        leverage: float = 1.0,
    ) -> dict | None:
        """
        side:
          "BUY"        — open long position
          "SELL_SHORT" — open short position
          "SELL"       — close long position
          "BUY_COVER"  — close short position
        """
        p = self.portfolios.get(shadow_id)
        if not p or price <= 0:
            return None

        if side in ("BUY", "SELL_SHORT"):
            direction = "long" if side == "BUY" else "short"
            lev = max(1.0, float(leverage or 1.0))
            margin_usd = size_usd
            if margin_usd <= 0 or margin_usd > p.capital:
                return None
            notional = margin_usd * lev
            qty = notional / price
            p.positions[symbol] = {
                "qty": qty,
                "entry_price": price,
                "entry_time": time.time(),
                "entry_capital": margin_usd,
                "margin_usd": margin_usd,
                "leverage": lev,
                "notional_usd": notional,
                "direction": direction,
            }
            p.capital -= margin_usd
            logger.debug(
                f"[{shadow_id}] OPEN {direction.upper()} {symbol} "
                f"lev={lev:.0f}x margin=${margin_usd:.0f} notional=${notional:.0f} @ {price:.4f}"
            )
            return {
                "action": "OPENED",
                "symbol": symbol,
                "qty": qty,
                "direction": direction,
                "leverage": lev,
                "margin_usd": margin_usd,
                "notional_usd": notional,
            }

        elif side in ("SELL", "BUY_COVER"):
            pos = p.positions.get(symbol)
            if not pos:
                return None
            pos_direction = pos.get("direction", "long")
            lev = max(1.0, float(pos.get("leverage", 1.0) or 1.0))
            margin = float(pos.get("margin_usd", pos.get("entry_capital", 0)) or 0)
            notional = float(pos.get("notional_usd", margin * lev) or margin * lev)
            if pos_direction == "long":
                pnl_pct = (price - pos["entry_price"]) / pos["entry_price"]
            else:
                pnl_pct = (pos["entry_price"] - price) / pos["entry_price"]

            side_fee = float(__import__("os").getenv("TRADE_FEE_PCT_PER_SIDE", "0.001"))
            fee_entry = notional * side_fee
            fee_exit = notional * side_fee
            gross_usd = margin * lev * pnl_pct
            net_usd = gross_usd - fee_entry - fee_exit
            net_pct = (net_usd / margin) if margin > 0 else pnl_pct - (side_fee * 2 * lev)
            p.capital += margin + net_usd
            trade = {
                "symbol": symbol, "shadow_id": shadow_id,
                "direction": pos_direction,
                "entry_price": pos["entry_price"], "exit_price": price,
                "leverage": lev,
                "margin_usd": margin,
                "notional_usd": notional,
                "pnl_pct": round(net_pct, 6),
                "pnl_usdt": round(net_usd, 4),
                "gross_pnl_usd": round(gross_usd, 4),
                "fee_total_usd": round(fee_entry + fee_exit, 4),
                "hold_seconds": round(time.time() - pos["entry_time"], 1),
                "closed_at": round(time.time(), 3),
            }
            p.trades.append(trade)
            del p.positions[symbol]
            logger.info(f"[{shadow_id}] CLOSE {pos_direction.upper()} {symbol} pnl={pnl_pct:.2%}")
            return trade

        return None

    def check_promotion(self, shadow_id: str) -> dict:
        p = self.portfolios.get(shadow_id)
        if not p:
            return {"eligible": False, "reason": "shadow not found"}
        c = PROMOTION_CRITERIA
        checks = {
            "trades": len(p.trades) >= c["min_trades"],
            "sharpe": p.sharpe_ratio >= c["min_sharpe"],
            "win_rate": p.win_rate >= c["min_win_rate"],
            "drawdown": p.max_drawdown <= c["max_drawdown"],
        }
        eligible = all(checks.values())
        return {
            "eligible": eligible, "shadow_id": shadow_id, "checks": checks,
            "metrics": {
                "sharpe": round(p.sharpe_ratio, 3),
                "win_rate": round(p.win_rate, 3),
                "trades": len(p.trades),
                "total_return": round(p.total_return, 4),
                "max_drawdown": round(p.max_drawdown, 4),
            }
        }

    def leaderboard(self) -> list[dict]:
        results = []
        for sid, p in self.portfolios.items():
            promo = self.check_promotion(sid)
            results.append({
                "shadow_id": sid, "sharpe": p.sharpe_ratio,
                "win_rate": p.win_rate, "trades": len(p.trades),
                "return": p.total_return, "promotion_ready": promo["eligible"],
                "checks": promo["checks"], "metrics": promo["metrics"],
            })
        return sorted(results, key=lambda x: x["sharpe"], reverse=True)
