"""
CVD (Cumulative Volume Delta) features.
Reads aggTrade list from Redis, computes buy/sell pressure over multiple windows.
"""
import json
import time


class CVDFeatureBuilder:
    def build(self, trades_raw: list, liq_raw: list) -> dict:
        now = time.time()
        features: dict[str, float] = {}

        # ── Parse trades ─────────────────────────────────────────────────────
        trades = []
        for r in trades_raw:
            try:
                item = json.loads(r) if isinstance(r, (str, bytes)) else r
                payload = item.get("data", item)
                qty   = float(payload.get("q", 0))
                ts_ms = float(payload.get("T", 0))
                is_buyer_maker = bool(payload.get("m", False))
                delta = -qty if is_buyer_maker else qty  # positive = buy pressure
                trades.append({"d": delta, "q": qty, "t": ts_ms / 1000})
            except Exception:
                continue

        # Windows: 5m, 15m, 1h
        windows = {"5m": 300, "15m": 900, "1h": 3600}
        for label, secs in windows.items():
            cutoff = now - secs
            recent = [t for t in trades if t["t"] >= cutoff]
            if recent:
                buy_vol  = sum(t["d"] for t in recent if t["d"] > 0)
                sell_vol = sum(-t["d"] for t in recent if t["d"] < 0)
                total    = buy_vol + sell_vol
                cvd      = buy_vol - sell_vol
                features[f"cvd_{label}"]      = float(cvd / total) if total else 0.0
                features[f"buy_ratio_{label}"] = float(buy_vol / total) if total else 0.5
            else:
                features[f"cvd_{label}"]      = 0.0
                features[f"buy_ratio_{label}"] = 0.5

        # CVD acceleration: compare last 5m vs prior 5m
        t1 = [t for t in trades if now - 300 <= t["t"] < now]
        t2 = [t for t in trades if now - 600 <= t["t"] < now - 300]
        def _net(ts): return sum(t["d"] for t in ts)
        n1, n2 = _net(t1), _net(t2)
        if abs(n2) > 0:
            features["cvd_acceleration"] = float((n1 - n2) / abs(n2))
        else:
            features["cvd_acceleration"] = 0.0

        # Whale detection: trades > 10× average size
        if trades:
            avg_size = sum(abs(t["d"]) for t in trades) / len(trades)
            whale_threshold = avg_size * 10
            recent_1h = [t for t in trades if t["t"] >= now - 3600]
            whale_buys  = sum(t["d"] for t in recent_1h if t["d"] > whale_threshold)
            whale_sells = sum(-t["d"] for t in recent_1h if -t["d"] > whale_threshold)
            whale_total = whale_buys + whale_sells
            features["whale_buy_ratio"] = float(whale_buys / whale_total) if whale_total > 0 else 0.5
        else:
            features["whale_buy_ratio"] = 0.5

        # ── Parse liquidations ────────────────────────────────────────────────
        long_liq = 0.0
        short_liq = 0.0
        for r in liq_raw:
            try:
                item = json.loads(r) if isinstance(r, (str, bytes)) else r
                usd  = float(item.get("usd", 0))
                side = item.get("side", "")
                ts   = float(item.get("t", 0))
                if ts < now - 3600:
                    continue
                if side == "SELL":   # long position liquidated
                    long_liq += usd
                elif side == "BUY":  # short position liquidated
                    short_liq += usd
            except Exception:
                continue

        total_liq = long_liq + short_liq
        features["liq_long_1h"]   = float(min(long_liq / 1_000_000, 10))
        features["liq_short_1h"]  = float(min(short_liq / 1_000_000, 10))
        features["liq_ratio_1h"]  = float((short_liq - long_liq) / total_liq) if total_liq > 0 else 0.0
        features["liq_usd_1h"]    = float(min(total_liq / 1_000_000, 10))

        return features
