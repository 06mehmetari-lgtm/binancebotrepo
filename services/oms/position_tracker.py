from dataclasses import dataclass

@dataclass
class Position:
    symbol: str
    side: str
    size: float
    entry_price: float
    unrealized_pnl: float = 0.0

class PositionTracker:
    def __init__(self):
        self._positions: dict[str, Position] = {}

    def update(self, symbol: str, side: str, size: float, entry_price: float, current_price: float):
        pnl = (current_price - entry_price) * size if side == "long" else (entry_price - current_price) * size
        self._positions[symbol] = Position(symbol, side, size, entry_price, pnl)

    def get(self, symbol: str) -> Position | None:
        return self._positions.get(symbol)

    def total_exposure(self) -> float:
        return sum(abs(p.size * p.entry_price) for p in self._positions.values())
