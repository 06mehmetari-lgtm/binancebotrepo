"""
Post-trade autopsy: computes PnL metrics, categorizes errors, feeds back to NEAT.
"""

import logging

logger = logging.getLogger(__name__)


class TradeAnalyzer:
    def analyze(self, trade: dict, market_context: dict) -> dict:
        entry = float(trade.get("entry_price", 0))
        exit_ = float(trade.get("exit_price", 0))
        side = trade.get("direction") or trade.get("side", "long")
        if side in ("BUY", "SELL"):
            side = "long" if side == "BUY" else "short"
        if side == "SELL_SHORT":
            side = "short"
        if side == "BUY_COVER":
            side = "short"
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
        reason = str(trade.get("exit_reason", "") or "")
        if pnl_pct > 0:
            if any(x in reason for x in ("Kâr kademesi", "Kâr hedefi", "Trailing", "Kârda sat")):
                return "PROFIT_TAKE"
            return "WIN"
        if "AI FLAT" in reason and hold_hours < 0.05:
            return "EARLY_FLAT_EXIT"
        peak = float(trade.get("peak_upnl_pct") or 0)
        if peak > 1.0 and pnl_pct <= 0:
            return "MISSED_PEAK"
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
