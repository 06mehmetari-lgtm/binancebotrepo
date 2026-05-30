import aiohttp
import asyncio
from kafka import KafkaProducer
import os

KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
SYMBOLS = ["BTCUSDT", "ETHUSDT"]

async def fetch_open_interest(producer: KafkaProducer):
    url = "https://fapi.binance.com/fapi/v1/openInterest"
    async with aiohttp.ClientSession() as session:
        while True:
            for symbol in SYMBOLS:
                async with session.get(url, params={"symbol": symbol}) as resp:
                    data = await resp.json()
                    producer.send("open_interest", data)
            await asyncio.sleep(30)
