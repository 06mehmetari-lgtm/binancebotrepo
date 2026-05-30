import json, redis, os, pickle

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

class GenomeManager:
    def __init__(self):
        self.r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)

    def save(self, genome_id: str, genome):
        self.r.set(f"genome:{genome_id}", pickle.dumps(genome))

    def load(self, genome_id: str):
        data = self.r.get(f"genome:{genome_id}")
        return pickle.loads(data) if data else None

    def list_genomes(self) -> list[str]:
        return [k.decode().split(":")[1] for k in self.r.keys("genome:*")]
