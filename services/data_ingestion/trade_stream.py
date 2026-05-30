import json
from dataclasses import dataclass

@dataclass
class Trade:
    symbol: str
    price: float
    qty: float
    is_buyer_maker: bool
    timestamp: int

    @classmethod
    def from_ws(cls, data: dict) -> "Trade":
        return cls(
            symbol=data["s"],
            price=float(data["p"]),
            qty=float(data["q"]),
            is_buyer_maker=data["m"],
            timestamp=data["T"],
        )
