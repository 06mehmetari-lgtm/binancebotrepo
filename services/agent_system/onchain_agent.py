"""On-chain agent — funding, OI, L/S ratio, exchange flows from Redis."""
import json
import os
import redis

_r = None

def _get_redis():
    global _r
    if _r is None:
        _r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True)
    return _r


class OnchainAgent:
    def analyze(self, context: dict) -> dict:
        symbol = context.get("symbol", "BTCUSDT")
        funding = 0.0
        ls_ratio = 1.0
        oi_change = 0.0
        try:
            r = _get_redis()
            f_raw = r.get(f"funding:{symbol}")
            if f_raw:
                funding = float(json.loads(f_raw).get("rate", 0))
            ls_raw = r.get(f"ls_ratio:{symbol}")
            if ls_raw:
                ls_ratio = float(json.loads(ls_raw).get("ls_ratio", 1))
            oi_raw = r.get(f"oi:{symbol}")
            if oi_raw:
                oi_change = float(json.loads(oi_raw).get("oi_change_pct", 0))
        except Exception:
            pass

        score = 0.0
        score -= funding * 100          # High funding → longs crowded → bearish
        score += (1 - ls_ratio) * 0.3  # More shorts → contrarian bullish
        score += oi_change / 30         # Rising OI with price = trend confirmation

        signal = "long" if score > 0.15 else ("short" if score < -0.15 else "flat")
        confidence = min(abs(score), 1.0)
        return {"agent": "onchain_agent", "signal": signal, "confidence": confidence,
                "reasoning": {"funding": funding, "ls_ratio": ls_ratio, "oi_change": oi_change}}
