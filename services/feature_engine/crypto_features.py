import numpy as np

class CryptoFeatureBuilder:
    def build(self, funding_rate: float, open_interest: float,
              prev_oi: float, liquidations_buy: float, liquidations_sell: float) -> dict:
        oi_change = (open_interest - prev_oi) / prev_oi if prev_oi else 0.0
        liq_ratio = (
            liquidations_buy / (liquidations_sell + 1e-9)
            if liquidations_sell > 0 else 1.0
        )
        return {
            "funding_rate": funding_rate,
            "open_interest": open_interest,
            "oi_change_pct": oi_change,
            "liq_ratio": liq_ratio,
            "liq_pressure": liquidations_buy + liquidations_sell,
        }
