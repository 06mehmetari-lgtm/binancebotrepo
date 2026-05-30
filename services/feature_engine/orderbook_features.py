import numpy as np

class OrderBookFeatureBuilder:
    def build(self, snapshot: dict) -> dict:
        if not snapshot or not snapshot.get("bids"):
            return {f"imbalance_{l}": 0.0 for l in [1, 3, 5, 10, 20]} | {
                "spread_pct": 0.0, "bid_pressure": 1.0, "ask_pressure": 1.0,
                "large_bid_ratio": 0.0, "large_ask_ratio": 0.0
            }
        bids = snapshot["bids"]
        asks = snapshot["asks"]
        features = {}
        for levels in [1, 3, 5, 10, 20]:
            bv = sum(b[1] for b in bids[:levels])
            av = sum(a[1] for a in asks[:levels])
            total = bv + av
            features[f"imbalance_{levels}"] = float((bv - av) / total) if total else 0.0
        features["spread_pct"] = float(snapshot.get("spread_pct", 0))
        near_bid = sum(b[1] for b in bids[:5])
        far_bid = sum(b[1] for b in bids[5:10]) or 1
        features["bid_pressure"] = float(near_bid / far_bid)
        near_ask = sum(a[1] for a in asks[:5])
        far_ask = sum(a[1] for a in asks[5:10]) or 1
        features["ask_pressure"] = float(near_ask / far_ask)
        avg_bid = np.mean([b[1] for b in bids[:10]]) if bids else 1
        features["large_bid_ratio"] = sum(1 for b in bids[:10] if b[1] > avg_bid * 3) / 10
        avg_ask = np.mean([a[1] for a in asks[:10]]) if asks else 1
        features["large_ask_ratio"] = sum(1 for a in asks[:10] if a[1] > avg_ask * 3) / 10
        return features
