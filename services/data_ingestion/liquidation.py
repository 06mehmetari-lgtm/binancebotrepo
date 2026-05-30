import asyncio
import json
import websockets
from kafka import KafkaProducer
import os

KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

async def stream_liquidations(producer: KafkaProducer):
    url = "wss://fstream.binance.com/ws/!forceOrder@arr"
    async with websockets.connect(url) as ws:
        async for msg in ws:
            data = json.loads(msg)
            producer.send("liquidations", data)
