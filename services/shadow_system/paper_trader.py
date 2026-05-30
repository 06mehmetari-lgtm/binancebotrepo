import time
from dataclasses import dataclass, field

@dataclass
class PaperPosition:
    symbol: str
    side: str
    size: float
    entry_price: float
    opened_at: int = field(default_factory=lambda: int(time.time() * 1000))

class PaperTrader:
    def __init__(self, initial_balance: float = 10_000.0):
        self.balance = initial_balance
        self.positions: dict[str, PaperPosition] = {}
        self.trades: list[dict] = []

    def open(self, symbol: str, side: str, size_usd: float, price: float):
        size = size_usd / price
        self.balance -= size_usd
        self.positions[symbol] = PaperPosition(symbol, side, size, price)

    def close(self, symbol: str, price: float) -> float:
        pos = self.positions.pop(symbol, None)
        if not pos:
            return 0.0
        pnl = (price - pos.entry_price) * pos.size if pos.side == "long" else (pos.entry_price - price) * pos.size
        self.balance += pos.size * price
        self.trades.append({"symbol": symbol, "pnl": pnl})
        return pnl

    @property
    def total_pnl(self) -> float:
        return sum(t["pnl"] for t in self.trades)
