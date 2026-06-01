"""
Crisis Detector — hard-trigger thresholds for market stress events.

Threshold calibration rationale:
- vix_spike: 30 → meaningful vol expansion in crypto correlated markets (was 40, almost never fired)
- btc_drop_1h: -5% → material 1-hour move that signals panic (was -10%, near impossible)
- liquidation_cascade: $10M → measurable cross-exchange liquidation event (was $100M, too rare)
- funding_extreme: ±0.001 → 0.1% per 8h is elevated; ±0.003 was 3× too permissive
- fear_greed_extreme: <15 = extreme fear, >85 = extreme greed
- spread_spike: bid-ask spread > 0.5% signals illiquid/panicky market
"""

CRISIS_THRESHOLDS = {
    "vix_spike":            30.0,       # VIX > 30 → elevated vol
    "btc_drop_1h":         -0.05,       # BTC -5% in 1h → flash crash territory
    "liquidation_cascade":  10_000_000, # $10M liquidated → cascade risk
    "funding_extreme":       0.001,     # |funding| > 0.1% per 8h → extreme positioning
    "fear_greed_extreme_low": 15.0,     # F&G < 15 → extreme fear
    "fear_greed_extreme_high": 85.0,    # F&G > 85 → extreme greed (often precedes dumps)
}


class CrisisDetector:
    def detect(self, metrics: dict) -> list[str]:
        triggers = []

        vix = metrics.get("vix", 0)
        if vix > CRISIS_THRESHOLDS["vix_spike"]:
            triggers.append("vix_spike")

        btc_ret = metrics.get("btc_return_1h", 0)
        if btc_ret < CRISIS_THRESHOLDS["btc_drop_1h"]:
            triggers.append("btc_flash_crash")

        liq_vol = metrics.get("liquidation_volume", 0)
        if liq_vol > CRISIS_THRESHOLDS["liquidation_cascade"]:
            triggers.append("liquidation_cascade")

        funding = metrics.get("funding_rate", 0)
        if abs(funding) > CRISIS_THRESHOLDS["funding_extreme"]:
            triggers.append("extreme_funding")

        fg = metrics.get("fear_greed", -1)
        if 0 <= fg < CRISIS_THRESHOLDS["fear_greed_extreme_low"]:
            triggers.append("extreme_fear")
        elif fg > CRISIS_THRESHOLDS["fear_greed_extreme_high"]:
            triggers.append("extreme_greed")

        return triggers
