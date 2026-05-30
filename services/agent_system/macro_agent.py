"""Macro agent — VIX, DXY, FRED yield curve from Redis."""
import json
import os
import redis

_r = None

def _get_redis():
    global _r
    if _r is None:
        _r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True)
    return _r


class MacroAgent:
    def analyze(self, context: dict) -> dict:
        vix = 20.0
        dxy_change = 0.0
        t10y2y = 0.5
        try:
            r = _get_redis()
            vix_raw = r.get("macro:vix")
            if vix_raw:
                vix = float(json.loads(vix_raw).get("value", 20))
            dxy_raw = r.get("macro:dxy")
            if dxy_raw:
                dxy_change = float(json.loads(dxy_raw).get("change_pct", 0))
            fred_raw = r.get("macro:fred:T10Y2Y")
            if fred_raw:
                t10y2y = float(json.loads(fred_raw).get("value", 0.5))
        except Exception:
            pass

        score = 0.0
        score -= (vix - 20) / 40         # High VIX → bearish
        score -= dxy_change / 2          # DXY up → crypto down
        score += min(t10y2y / 2, 0.5)   # Positive yield curve → mild bullish

        signal = "long" if score > 0.1 else ("short" if score < -0.1 else "flat")
        confidence = min(abs(score), 1.0)
        return {"agent": "macro_agent", "signal": signal, "confidence": confidence,
                "reasoning": {"vix": vix, "dxy_change": dxy_change, "t10y2y": t10y2y}}
