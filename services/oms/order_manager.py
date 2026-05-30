import uuid, time
from dataclasses import dataclass, field
from typing import Literal

OrderStatus = Literal["pending", "filled", "cancelled", "rejected"]

@dataclass
class Order:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str = ""
    side: str = ""
    qty: float = 0.0
    price: float | None = None
    status: OrderStatus = "pending"
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))

class OrderManager:
    def __init__(self):
        self._orders: dict[str, Order] = {}

    def create(self, symbol: str, side: str, qty: float, price: float | None = None) -> Order:
        order = Order(symbol=symbol, side=side, qty=qty, price=price)
        self._orders[order.id] = order
        return order

    def update_status(self, order_id: str, status: OrderStatus):
        if order_id in self._orders:
            self._orders[order_id].status = status

    def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)
