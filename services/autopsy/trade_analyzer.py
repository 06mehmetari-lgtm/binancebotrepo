"""
Post-trade autopsy: computes PnL metrics, categorizes errors, feeds back to NEAT.
"""

import logging

logger = logging.getLogger(__name__)


class TradeAnalyzer:
    def analyze(self, trade: dict, market_context: dict) -> dict:
        entry = float(trade.get("entry_price", 0))
        exit_ = float(trade.get("exit_price", 0))
        side = trade.get("side", "long")
        pnl_pct = ((exit_ - entry) / entry * (1 if side == "long" else -1)) if entry else 0

        was_profitable = pnl_pct > 0
        hold_hours = float(trade.get("hold_seconds", 0)) / 3600

        error_category = self._categorize(trade, market_context, pnl_pct, hold_hours)

        return {
            "trade_id": trade.get("id") or trade.get("trade_id"),
            "pnl_pct": pnl_pct,
            "was_winner": was_profitable,
            "hold_hours": hold_hours,
            "entry_regime": market_context.get("regime", "unknown"),
            "entry_vix": market_context.get("vix_level", 0),
            "entry_funding": market_context.get("funding_rate", 0),
            "entry_crisis_level": market_context.get("crisis_level", 0),
            "drift_at_entry": market_context.get("drift_status", "STABLE"),
            "error_category": error_category,
            "confidence": float(trade.get("confidence", 0)),
        }

    def _categorize(self, trade: dict, ctx: dict, pnl_pct: float, hold_hours: float) -> str:
        if pnl_pct > 0:
            return "WIN"
        drift = ctx.get("drift_status", "STABLE")
        if drift in ("DRIFTING", "SHOCK"):
            return "DRIFT_IGNORED"
        if hold_hours > 24:
            return "EXIT_TIMING"
        if float(trade.get("confidence", 0)) > 0.8:
            return "OVERCONFIDENCE"
        regime = ctx.get("regime", "unknown")
        if regime not in ("unknown", ""):
            return "REGIME_MISMATCH"
        return "MARKET_SHOCK"
