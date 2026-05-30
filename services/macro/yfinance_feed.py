import asyncio, json, os
import yfinance as yf
from kafka import KafkaProducer

KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
TICKERS = ["^VIX", "DX-Y.NYB", "SPY", "GLD", "TLT"]

class YFinanceFeed:
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode()
        )

    async def run(self):
        while True:
            await asyncio.get_event_loop().run_in_executor(None, self._fetch)
            await asyncio.sleep(300)

    def _fetch(self):
        for ticker in TICKERS:
            data = yf.download(ticker, period="1d", interval="1m", progress=False)
            if not data.empty:
                row = data.iloc[-1]
                self.producer.send("macro_market", {
                    "ticker": ticker,
                    "close": float(row["Close"]),
                    "volume": float(row["Volume"]),
                })
