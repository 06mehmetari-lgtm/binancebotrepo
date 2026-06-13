"""Ticker yoksa features/kline'dan fiyat — guard ve shadow için."""

from __future__ import annotations

import json
from typing import Any


def _price_from_dict(data: dict[str, Any]) -> float:
    for key in ("close", "last_price", "mark_price", "c", "price"):
        try:
            p = float(data.get(key) or 0)
        except (TypeError, ValueError):
            p = 0.0
        if p > 0:
            return p
    return 0.0


def mid_from_ticker_raw(raw: str | bytes | None) -> float:
    if not raw:
        return 0.0
    try:
        t = json.loads(raw)
        d = t.get("data", t)
        bid = float(d.get("b", 0) or 0)
        ask = float(d.get("a", bid) or bid)
        if bid > 0:
            return (bid + ask) / 2 if ask > 0 else bid
        return ask
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0.0


def price_from_features_raw(raw: str | bytes | None) -> float:
    if not raw:
        return 0.0
    try:
        return _price_from_dict(json.loads(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0.0


async def resolve_market_price(redis, symbol: str) -> float:
    sym = symbol.upper()
    sym_l = sym.lower()
    pipe = redis.pipeline()
    pipe.get(f"binance:ticker:{sym_l}")
    pipe.get(f"features:latest:{sym}")
    pipe.lindex(f"binance:kline:{sym_l}", 0)
    ticker_raw, feat_raw, kline_raw = await pipe.execute()

    price = mid_from_ticker_raw(ticker_raw)
    if price > 0:
        return price

    price = price_from_features_raw(feat_raw)
    if price > 0:
        return price

    if kline_raw:
        try:
            k = json.loads(kline_raw)
            payload = k.get("data", k)
            if isinstance(payload, dict) and payload.get("k"):
                return float(payload["k"].get("c", 0) or 0)
            return _price_from_dict(payload)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return 0.0
