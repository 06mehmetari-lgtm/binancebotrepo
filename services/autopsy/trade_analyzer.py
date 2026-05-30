import numpy as np

class TradeAnalyzer:
    def analyze(self, trade: dict, market_context: dict) -> dict:
        entry = trade.get("entry_price", 0)
        exit_ = trade.get("exit_price", 0)
        side = trade.get("side", "long")
        pnl_pct = ((exit_ - entry) / entry * (1 if side == "long" else -1)) if entry else 0
        return {
            "trade_id": trade.get("id"),
            "pnl_pct": pnl_pct,
            "was_winner": pnl_pct > 0,
            "entry_regime": market_context.get("regime", "unknown"),
            "entry_vix": market_context.get("vix", 0),
            "entry_funding": market_context.get("funding_rate", 0),
        }
