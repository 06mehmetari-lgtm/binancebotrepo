import asyncio, aiohttp, json, os
from kafka import KafkaProducer

KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")

class CryptoPanicFeed:
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode()
        )

    async def run(self):
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={API_KEY}&public=true"
        async with aiohttp.ClientSession() as session:
            while True:
                async with session.get(url) as resp:
                    data = await resp.json()
                    for item in data.get("results", []):
                        self.producer.send("news_feed", item)
                await asyncio.sleep(60)
