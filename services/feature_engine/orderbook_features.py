import numpy as np

class OrderBookFeatureBuilder:
    def build(self, bids: list, asks: list) -> dict:
        bid_prices = np.array([b[0] for b in bids])
        bid_vols = np.array([b[1] for b in bids])
        ask_prices = np.array([a[0] for a in asks])
        ask_vols = np.array([a[1] for a in asks])

        total_bid = bid_vols.sum()
        total_ask = ask_vols.sum()
        total = total_bid + total_ask

        return {
            "imbalance": (total_bid - total_ask) / total if total else 0.0,
            "spread": ask_prices[0] - bid_prices[0] if len(ask_prices) and len(bid_prices) else 0.0,
            "bid_depth_5": total_bid,
            "ask_depth_5": total_ask,
            "mid_price": (ask_prices[0] + bid_prices[0]) / 2 if len(ask_prices) and len(bid_prices) else 0.0,
        }
