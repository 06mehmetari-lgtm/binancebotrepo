import asyncio, aiohttp, json, os
from kafka import KafkaProducer

KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
ETHERSCAN_KEY = os.getenv("ETHERSCAN_API_KEY", "")

class OnChainFeed:
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode()
        )

    async def run(self):
        async with aiohttp.ClientSession() as session:
            while True:
                await self._fetch_gas(session)
                await asyncio.sleep(60)

    async def _fetch_gas(self, session: aiohttp.ClientSession):
        url = f"https://api.etherscan.io/api?module=gastracker&action=gasoracle&apikey={ETHERSCAN_KEY}"
        async with session.get(url) as resp:
            data = await resp.json()
            self.producer.send("onchain_gas", data.get("result", {}))
