import asyncio
import json
import websockets
import os
from kafka import KafkaProducer

KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
SYMBOLS = ["btcusdt", "ethusdt"]

class BinanceWebSocket:
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode()
        )

    async def _stream(self, url: str, topic: str):
        async with websockets.connect(url) as ws:
            async for msg in ws:
                data = json.loads(msg)
                self.producer.send(topic, data)

    async def run(self):
        streams = "/".join(f"{s}@aggTrade/{s}@depth5@100ms" for s in SYMBOLS)
        url = f"wss://fstream.binance.com/stream?streams={streams}"
        await self._stream(url, "raw_market_data")
