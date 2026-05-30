import numpy as np

CRISIS_THRESHOLDS = {
    "vix_spike": 40.0,
    "btc_drop_1h": -0.10,
    "liquidation_cascade": 100_000_000,
    "funding_extreme": 0.003,
}

class CrisisDetector:
    def detect(self, metrics: dict) -> list[str]:
        triggers = []
        if metrics.get("vix", 0) > CRISIS_THRESHOLDS["vix_spike"]:
            triggers.append("vix_spike")
        if metrics.get("btc_return_1h", 0) < CRISIS_THRESHOLDS["btc_drop_1h"]:
            triggers.append("btc_flash_crash")
        if metrics.get("liquidation_volume", 0) > CRISIS_THRESHOLDS["liquidation_cascade"]:
            triggers.append("liquidation_cascade")
        if abs(metrics.get("funding_rate", 0)) > CRISIS_THRESHOLDS["funding_extreme"]:
            triggers.append("extreme_funding")
        return triggers
