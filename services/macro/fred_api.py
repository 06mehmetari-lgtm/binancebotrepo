import asyncio, json, os
from fredapi import Fred
from kafka import KafkaProducer

KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
FRED_KEY = os.getenv("FRED_API_KEY", "")

SERIES = ["DFF", "T10Y2Y", "CPIAUCSL", "UNRATE", "M2SL"]

class FredFeed:
    def __init__(self):
        self.fred = Fred(api_key=FRED_KEY)
        self.producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode()
        )

    async def run(self):
        loop = asyncio.get_event_loop()
        while True:
            await loop.run_in_executor(None, self._fetch)
            await asyncio.sleep(3600)

    def _fetch(self):
        for series_id in SERIES:
            data = self.fred.get_series(series_id).dropna().tail(1)
            self.producer.send("macro_fred", {
                "series": series_id,
                "value": float(data.iloc[-1]),
                "date": str(data.index[-1].date()),
            })
