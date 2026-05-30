import aiohttp
import asyncio
import json
from kafka import KafkaProducer
import os

KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

async def fetch_funding_rates(producer: KafkaProducer):
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(url) as resp:
                data = await resp.json()
                for item in data:
                    producer.send("funding_rate", item)
            await asyncio.sleep(60)
