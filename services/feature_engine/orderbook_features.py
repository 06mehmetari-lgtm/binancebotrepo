"""Order book depth features — multi-level bid/ask imbalance and ladder stats."""

import numpy as np

LEVELS = [1, 3, 5, 10, 20]


def _normalize_depth_event(raw: dict) -> dict:
    """Binance depthUpdate uses b/a; snapshots use bids/asks."""
    if raw.get("bids") or raw.get("asks"):
        return raw
    bids = [[float(p), float(q)] for p, q in raw.get("b", []) if float(q) > 0]
    asks = [[float(p), float(q)] for p, q in raw.get("a", []) if float(q) > 0]
    if not bids or not asks:
        return {}
    best_bid = bids[0][0]
    best_ask = asks[0][0]
    mid = (best_bid + best_ask) / 2
    spread = best_ask - best_bid
    return {
        "bids": bids,
        "asks": asks,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid_price": mid,
        "spread_pct": spread / mid * 100 if mid else 0,
    }


class OrderBookFeatureBuilder:
    def build(self, snapshot: dict) -> dict:
        snapshot = _normalize_depth_event(snapshot or {})
        empty = (
            {f"imbalance_{l}": 0.0 for l in LEVELS}
            | {f"bid_qty_l{i}": 0.0 for i in range(1, 6)}
            | {f"ask_qty_l{i}": 0.0 for i in range(1, 6)}
            | {
                "spread_pct": 0.0,
                "bid_pressure": 1.0,
                "ask_pressure": 1.0,
                "large_bid_ratio": 0.0,
                "large_ask_ratio": 0.0,
                "bid_levels_active": 0,
                "ask_levels_active": 0,
                "depth_bid_total": 0.0,
                "depth_ask_total": 0.0,
            }
        )
        if not snapshot or not snapshot.get("bids"):
            return empty

        bids = snapshot["bids"]
        asks = snapshot["asks"]
        features: dict = {}

        for levels in LEVELS:
            bv = sum(b[1] for b in bids[:levels])
            av = sum(a[1] for a in asks[:levels])
            total = bv + av
            features[f"imbalance_{levels}"] = float((bv - av) / total) if total else 0.0
            if levels == 20:
                features["depth_bid_total"] = float(bv)
                features["depth_ask_total"] = float(av)

        features["spread_pct"] = float(snapshot.get("spread_pct", 0))
        features["bid_levels_active"] = min(len(bids), 20)
        features["ask_levels_active"] = min(len(asks), 20)

        for i in range(5):
            features[f"bid_qty_l{i + 1}"] = float(bids[i][1]) if i < len(bids) else 0.0
            features[f"ask_qty_l{i + 1}"] = float(asks[i][1]) if i < len(asks) else 0.0

        near_bid = sum(b[1] for b in bids[:5])
        far_bid = sum(b[1] for b in bids[5:10]) or 1
        features["bid_pressure"] = float(near_bid / far_bid)
        near_ask = sum(a[1] for a in asks[:5])
        far_ask = sum(a[1] for a in asks[5:10]) or 1
        features["ask_pressure"] = float(near_ask / far_ask)

        avg_bid = np.mean([b[1] for b in bids[:10]]) if bids else 1
        features["large_bid_ratio"] = sum(1 for b in bids[:10] if b[1] > avg_bid * 3) / max(len(bids[:10]), 1)
        avg_ask = np.mean([a[1] for a in asks[:10]]) if asks else 1
        features["large_ask_ratio"] = sum(1 for a in asks[:10] if a[1] > avg_ask * 3) / max(len(asks[:10]), 1)

        return features
