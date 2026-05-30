"""Genome manager — persists NEAT genomes to PostgreSQL rule_genomes table."""
import json
import logging
import asyncpg

logger = logging.getLogger(__name__)


class GenomeManager:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self._db: asyncpg.Connection | None = None

    async def connect(self):
        try:
            self._db = await asyncpg.connect(self.db_url)
            logger.info("GenomeManager connected to PostgreSQL")
        except Exception as e:
            logger.warning(f"GenomeManager DB connection failed: {e}")

    async def save(self, genome_data: dict):
        if not self._db:
            return
        try:
            await self._db.execute("""
                INSERT INTO rule_genomes
                (genome_id, generation, status, topology_nodes, topology_conns,
                 topology_json, fitness_score, win_rate, sharpe_ratio)
                VALUES ($1, $2, 'TRIAL', $3, $4, $5, $6, 0, 0)
                ON CONFLICT (genome_id) DO UPDATE SET
                    fitness_score = EXCLUDED.fitness_score,
                    updated_at = NOW()
            """,
                genome_data.get("genome_id", "unknown"),
                int(genome_data.get("generation", 1)),
                int(genome_data.get("nodes", 0)),
                int(genome_data.get("connections", 0)),
                genome_data.get("topology_json", "{}"),
                float(genome_data.get("fitness", 0)),
            )
            logger.info(f"Genome saved: {genome_data.get('genome_id')} fitness={genome_data.get('fitness', 0):.3f}")
        except Exception as e:
            logger.error(f"Genome save error: {e}")

    async def promote(self, genome_id: str):
        if not self._db:
            return
        await self._db.execute(
            "UPDATE rule_genomes SET status='ACTIVE', updated_at=NOW() WHERE genome_id=$1",
            genome_id
        )

    async def retire(self, genome_id: str, reason: str = ""):
        if not self._db:
            return
        await self._db.execute(
            "UPDATE rule_genomes SET status='DEAD', death_reason=$1, archived_at=NOW(), updated_at=NOW() WHERE genome_id=$2",
            reason, genome_id
        )

    async def get_best(self, symbol: str | None = None) -> dict | None:
        if not self._db:
            return None
        try:
            row = await self._db.fetchrow(
                "SELECT * FROM rule_genomes WHERE status IN ('ACTIVE','TRIAL') ORDER BY fitness_score DESC LIMIT 1"
            )
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Genome fetch error: {e}")
            return None
