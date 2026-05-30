"""
Local Order Book — synced with Binance diff depth stream.
"""

import asyncio
import json
import logging
from decimal import Decimal
import httpx

logger = logging.getLogger(__name__)


class LocalOrderBook:
    def __init__(self, symbol: str, depth: int = 20):
        self.symbol = symbol.upper()
        self.depth = depth
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.last_update_id: int = 0
        self._event_buffer: list[dict] = []
        self._initialized = False
        self._snapshot_pending = False

    async def initialize(self):
        logger.info(f"Initializing order book: {self.symbol}")
        self._snapshot_pending = True
        params = {"symbol": self.symbol, "limit": 1000}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.binance.com/api/v3/depth", params=params)
            data = resp.json()
        self.last_update_id = data["lastUpdateId"]
        self.bids = {Decimal(p): Decimal(q) for p, q in data["bids"] if Decimal(q) > 0}
        self.asks = {Decimal(p): Decimal(q) for p, q in data["asks"] if Decimal(q) > 0}
        for event in self._event_buffer:
            self._apply(event)
        self._event_buffer.clear()
        self._initialized = True
        self._snapshot_pending = False
        logger.info(f"Order book ready: {self.symbol} (updateId={self.last_update_id})")

    def process_event(self, event: dict):
        if self._snapshot_pending:
            self._event_buffer.append(event)
            return
        if not self._initialized:
            return
        if event.get("u", 0) <= self.last_update_id:
            return
        if event.get("U", 0) > self.last_update_id + 1:
            logger.warning(f"Order book gap detected for {self.symbol}, reinitializing")
            asyncio.create_task(self.initialize())
            return
        self._apply(event)

    def _apply(self, event: dict):
        for p, q in event.get("b", []):
            price = Decimal(p)
            qty = Decimal(q)
            if qty == 0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = qty
        for p, q in event.get("a", []):
            price = Decimal(p)
            qty = Decimal(q)
            if qty == 0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = qty
        self.last_update_id = event.get("u", self.last_update_id)

    def snapshot(self, levels: int = 10) -> dict:
        top_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:levels]
        top_asks = sorted(self.asks.items(), key=lambda x: x[0])[:levels]
        if not top_bids or not top_asks:
            return {}
        best_bid = float(top_bids[0][0])
        best_ask = float(top_asks[0][0])
        mid = (best_bid + best_ask) / 2
        spread = best_ask - best_bid
        bid_depth = sum(float(p) * float(q) for p, q in top_bids)
        ask_depth = sum(float(p) * float(q) for p, q in top_asks)
        total = bid_depth + ask_depth
        return {
            "symbol": self.symbol,
            "bids": [[float(p), float(q)] for p, q in top_bids],
            "asks": [[float(p), float(q)] for p, q in top_asks],
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid,
            "spread": spread,
            "spread_pct": spread / mid * 100 if mid else 0,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "imbalance": (bid_depth - ask_depth) / total if total else 0,
        }
