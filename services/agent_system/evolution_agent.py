"""Evolution agent — reads best NEAT genome fitness from Redis to inform confidence."""
import json
import os
import redis

_r = None

def _get_redis():
    global _r
    if _r is None:
        _r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True)
    return _r


class EvolutionAgent:
    def analyze(self, context: dict) -> dict:
        symbol = context.get("symbol", "BTCUSDT")
        best_fitness = 0.0
        neat_signal = "flat"
        try:
            r = _get_redis()
            genome_raw = r.get(f"neat:best_genome:{symbol}")
            if genome_raw:
                genome = json.loads(genome_raw)
                best_fitness = float(genome.get("fitness", 0))
                # High fitness NEAT genome supports current trend
                if best_fitness > 2.0:
                    neat_signal = "long"  # simplified — NEAT suggests strong signal
                elif best_fitness > 1.0:
                    neat_signal = "flat"
        except Exception:
            pass

        confidence = min(best_fitness / 3.0, 1.0)
        return {"agent": "evolution_agent", "signal": neat_signal, "confidence": confidence,
                "reasoning": {"best_fitness": best_fitness}}
