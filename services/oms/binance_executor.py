import ccxt, os

class BinanceExecutor:
    def __init__(self):
        self.exchange = ccxt.binanceusdm({
            "apiKey": os.getenv("BINANCE_API_KEY"),
            "secret": os.getenv("BINANCE_API_SECRET"),
            "options": {"defaultType": "future"},
        })
        if os.getenv("BINANCE_TESTNET", "true").lower() == "true":
            self.exchange.set_sandbox_mode(True)

    def market_order(self, symbol: str, side: str, amount: float) -> dict:
        return self.exchange.create_market_order(symbol, side, amount)

    def limit_order(self, symbol: str, side: str, amount: float, price: float) -> dict:
        return self.exchange.create_limit_order(symbol, side, amount, price)

    def cancel_order(self, order_id: str, symbol: str) -> dict:
        return self.exchange.cancel_order(order_id, symbol)

    def get_positions(self) -> list:
        return self.exchange.fetch_positions()
