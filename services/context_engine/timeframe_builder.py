import pandas as pd

TIMEFRAMES = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "D"}

class TimeframeBuilder:
    def resample(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        rule = TIMEFRAMES.get(timeframe, timeframe)
        return df.resample(rule).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()
