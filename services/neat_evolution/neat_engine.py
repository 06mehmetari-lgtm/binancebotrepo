"""
NEAT Trading Engine — evolves rule genomes using neat-python.
Fitness = Sharpe × win_rate × (1 - max_drawdown) on historical feature data.
"""

import logging
import os
import json
import asyncio
import numpy as np
import neat

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "neat.config")


class NEATTradingEngine:
    def __init__(self, db_url: str | None = None, symbol: str = "BTCUSDT"):
        self.config = neat.Config(
            neat.DefaultGenome, neat.DefaultReproduction,
            neat.DefaultSpeciesSet, neat.DefaultStagnation, CONFIG_PATH,
        )
        self.db_url = db_url
        self.symbol = symbol
        self._features: np.ndarray | None = None
        self._prices: np.ndarray | None = None

    async def load_training_data(self):
        """Load historical features from DB. Falls back to synthetic data."""
        if self.db_url is None:
            self._generate_synthetic_data()
            return
        try:
            import asyncpg
            conn = await asyncpg.connect(self.db_url)
            rows = await conn.fetch(
                "SELECT rsi_14, macd_hist, bb_position, atr_14, adx_14, "
                "imbalance_5, funding_rate, oi_change_1h, fear_greed_norm, vix_level "
                "FROM features WHERE symbol = $1 ORDER BY time ASC LIMIT 5000",
                self.symbol
            )
            await conn.close()
            if len(rows) < 100:
                self._generate_synthetic_data()
                return
            self._features = np.array([[float(v or 0) for v in row] for row in rows], dtype=np.float32)
            # Synthetic price series if no price available
            self._prices = np.cumprod(1 + np.random.randn(len(rows)) * 0.001) * 50_000
            logger.info(f"NEAT training data loaded: {len(rows)} samples")
        except Exception as e:
            logger.warning(f"DB load failed ({e}), using synthetic data")
            self._generate_synthetic_data()

    def _generate_synthetic_data(self):
        n = 2000
        self._features = np.random.randn(n, 10).astype(np.float32)
        self._prices = np.cumprod(1 + np.random.randn(n) * 0.001) * 50_000
        logger.info("Using synthetic training data")

    def evaluate_genome(self, genome, config) -> float:
        """
        Walk-forward simulation on features/prices.
        No lookahead: entry and exit both use price[i] (current bar close).
        Fee of 0.1% round-trip deducted from each trade.
        Position size is confidence-proportional (max 5%).
        """
        if self._features is None:
            return 0.0
        net = neat.nn.FeedForwardNetwork.create(genome, config)
        capital = 10_000.0
        position = 0.0
        entry_price = 0.0
        trades = []
        equity = [capital]
        FEE = 0.001  # 0.1% round-trip

        for i in range(len(self._features)):
            output = net.activate(self._features[i].tolist())
            action = int(np.argmax(output))  # 0=BUY, 1=SELL, 2=HOLD
            conf   = float(np.max(output))
            price  = float(self._prices[i])

            if action == 0 and conf > 0.55 and position == 0:
                # Enter long: size proportional to confidence
                size = capital * min(0.05, 0.03 * conf)
                position = size / price
                entry_price = price
                capital -= size

            elif action == 1 and position > 0:
                # Exit long at current bar (no lookahead)
                exit_val = position * price
                raw_pnl = (price - entry_price) / entry_price
                pnl = raw_pnl - FEE
                capital += exit_val
                trades.append(pnl)
                position = 0.0
                entry_price = 0.0

            # Equity at current price — no lookahead
            equity.append(capital + position * price)

        # Force-close any open position at last bar
        if position > 0:
            last_price = float(self._prices[-1])
            exit_val = position * last_price
            pnl = (last_price - entry_price) / entry_price - FEE
            capital += exit_val
            trades.append(pnl)
            equity.append(capital)

        if len(trades) < 5:
            return 0.0

        returns = np.array(trades)
        std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 1e-9
        sharpe = float(np.mean(returns) / max(std, 1e-9) * np.sqrt(252))
        win_rate = float(np.sum(returns > 0) / len(returns))
        eq_arr = np.array(equity)
        peak = np.maximum.accumulate(eq_arr)
        max_dd = float(np.max((peak - eq_arr) / np.maximum(peak, 1e-6)))

        # Composite fitness: bounded to avoid domination by single metric
        sharpe_norm = min(sharpe, 3.0) / 3.0        # normalise to [0, 1]
        fitness = sharpe_norm * win_rate * (1 - max_dd)

        # Bonus for active strategies with enough trades (not cash-sitters)
        if len(trades) >= 20:
            fitness *= 1.1
        if len(trades) >= 50:
            fitness *= 1.1

        return max(0.0, fitness)

    def run(self, generations: int = 50) -> dict:
        if self._features is None:
            raise RuntimeError("Call load_training_data() first")

        pop = neat.Population(self.config)
        pop.add_reporter(neat.StdOutReporter(True))
        stats = neat.StatisticsReporter()
        pop.add_reporter(stats)

        def eval_genomes(genomes, config):
            for _, genome in genomes:
                genome.fitness = self.evaluate_genome(genome, config)

        best = pop.run(eval_genomes, generations)
        species_count = len(pop.species.species) if hasattr(pop, 'species') else 1
        genome_count = sum(len(s.members) for s in pop.species.species.values()) if hasattr(pop, 'species') else 0
        logger.info(f"NEAT best fitness: {best.fitness:.4f}")

        return {
            "genome_id": f"NEAT_{id(best) % 100000}",
            "fitness": float(best.fitness),
            "nodes": len(best.nodes),
            "connections": len(best.connections),
            "generation": generations,
            "species_count": species_count,
            "genome_count": genome_count,
            "topology_json": json.dumps({
                "nodes": list(best.nodes.keys()),
                "connections": {f"{k[0]}_{k[1]}": v.enabled for k, v in best.connections.items()}
            }),
        }
