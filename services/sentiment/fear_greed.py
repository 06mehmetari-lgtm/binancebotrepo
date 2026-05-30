import asyncio, aiohttp, json, os
from kafka import KafkaProducer

KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

class FearGreedIndex:
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode()
        )

    async def run(self):
        url = "https://api.alternative.me/fng/?limit=1"
        async with aiohttp.ClientSession() as session:
            while True:
                async with session.get(url) as resp:
                    data = await resp.json()
                    self.producer.send("fear_greed", data["data"][0])
                await asyncio.sleep(3600)
