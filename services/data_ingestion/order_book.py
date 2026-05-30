import json
from collections import defaultdict

class OrderBook:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}

    def update(self, data: dict):
        for price, qty in data.get("b", []):
            p, q = float(price), float(qty)
            if q == 0:
                self.bids.pop(p, None)
            else:
                self.bids[p] = q
        for price, qty in data.get("a", []):
            p, q = float(price), float(qty)
            if q == 0:
                self.asks.pop(p, None)
            else:
                self.asks[p] = q

    def best_bid(self) -> float:
        return max(self.bids) if self.bids else 0.0

    def best_ask(self) -> float:
        return min(self.asks) if self.asks else 0.0

    def spread(self) -> float:
        return self.best_ask() - self.best_bid()

    def imbalance(self, depth: int = 5) -> float:
        bids = sorted(self.bids.items(), reverse=True)[:depth]
        asks = sorted(self.asks.items())[:depth]
        bid_vol = sum(v for _, v in bids)
        ask_vol = sum(v for _, v in asks)
        total = bid_vol + ask_vol
        return (bid_vol - ask_vol) / total if total else 0.0
