# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Prometheus Trading System** — a fully containerized, multi-service algorithmic cryptocurrency trading bot targeting Binance USDM Futures. It combines classical technical analysis, on-chain data, macro signals, NLP sentiment, NEAT-evolved trading rules, PPO reinforcement learning, and a 9-agent LLM debate system (using the Anthropic Claude API) to produce trade signals.

## Commands

### Full system
```bash
make up          # Start all services (docker compose up -d)
make down        # Stop all services
make build       # Rebuild all Docker images
make logs        # Tail all service logs
make ps          # Show running containers
make clean       # Remove containers + volumes (destructive)
```

### Restart a single service
```bash
make restart-<service_name>
# e.g.: make restart-signal_engine
```

### Infrastructure only (no app services)
```bash
make infra       # Starts: postgres, timescale, redis, qdrant, grafana, prometheus_metrics
```

### Individual service (local dev, outside Docker)
```bash
cd services/<service_name>
pip install -r requirements.txt
python main.py
```

### Dashboard (Next.js)
```bash
cd services/dashboard
npm install
npm run dev   # dev server on port 3000
npm run build
```

## Environment Setup

Copy `.env.example` to `.env` and fill in credentials. Key variables:

| Variable | Purpose |
|---|---|
| `BINANCE_API_KEY` / `BINANCE_SECRET` | Binance USDM Futures access |
| `DRY_RUN` | `true` = testnet/paper mode (default), `false` = live |
| `TRADING_SYMBOLS` | Comma-separated, e.g. `BTCUSDT,ETHUSDT,BNBUSDT` |
| `ANTHROPIC_API_KEY` | Required by all 9 agents in `agent_system` |
| `FRED_API_KEY` | Macro economic data |
| `ETHERSCAN_KEY` | On-chain metrics |
| `CRYPTOPANIC_KEY` / `REDDIT_*` | Sentiment feeds |

**Always keep `DRY_RUN=true` until the shadow system has promoted a strategy (see Shadow System below).**

## Architecture

### Data Flow (top-to-bottom pipeline)

```
Binance WebSocket (futures stream)
    └─► data_ingestion  ──Kafka──►  raw_market_data topic
            │
            └─► TimescaleDB (market_ticks, order_book_snapshots, klines, crypto_metrics)

sentiment + macro  ──Redis──►  feature_engine
                                    │
                                    └─► TimescaleDB (features table)
                                    └─► drift_detector (ADWIN + DDM + KL divergence)

context_engine  (reads features from Redis/TSDB)
    ├─ RegimeClassifier  — GMM (4 components): trending_up/down, ranging, volatile
    └─ CrisisDetector    — hard triggers: VIX > 40, BTC -10% in 1h, $100M liquidations, extreme funding

agent_system  (reads context + features)
    ├─ BullAgent       — argues long
    ├─ BearAgent       — argues short
    ├─ NeutralAgent    — balanced view
    ├─ TechnicalAgent  — price/indicator analysis
    ├─ NewsAgent       — news sentiment
    ├─ MacroAgent      — macro correlation
    ├─ OnChainAgent    — on-chain flows
    ├─ RiskAgent       — VaR, Kelly, drawdown
    ├─ EvolutionAgent  — NEAT genome lifecycle
    └─ DebateAgent     — moderates Bull vs Bear, synthesizes verdict (JSON: direction, confidence, consensus_reasoning, dissent_risk)

signal_engine  (aggregates agent votes)
    ├─ SignalGenerator  — confidence-weighted vote; direction suppressed to "flat" if confidence < 0.60
    └─ KellyCalculator  — position size = min(kelly_fraction, 5% of portfolio)

immunity_system  (hard limits, check every order BEFORE execution)
    └─ ImmunitySystem.check_order()  — enforces:
         • max leverage: 3×
         • max position: 5% of portfolio per trade
         • max daily loss: 2% of portfolio
         • max open positions: 3

shadow_system  (paper trading gate)
    ├─ PaperTrader      — simulates fills without real orders
    ├─ ShadowEvaluator  — tracks paper P&L
    └─ PromotionEngine  — promotes to live when: ≥100 trades, Sharpe ≥ 1.5, win rate ≥ 52%, max drawdown < 10%

oms  (Order Management System — only reached after immunity + shadow promotion)
    ├─ BinanceExecutor  — ccxt binanceusdm, sandbox mode when BINANCE_TESTNET=true
    ├─ OrderManager     — order lifecycle
    ├─ PositionTracker
    └─ AuditLogger

autopsy  (post-trade analysis)
    ├─ TradeAnalyzer    — calculates PnL %, labels entry regime/VIX/funding
    ├─ QuestionEngine   — generates structured post-mortem questions
    └─ MemoryWriter     — stores results in Qdrant (via rag_memory)

neat_evolution  (strategy evolution, CPU/memory intensive: 2 CPU / 4 GB limit)
    ├─ NEATEngine       — wraps neat-python, config in neat.config
    ├─ GenomeManager    — CRUD for rule genomes in PostgreSQL
    ├─ SpeciesManager
    └─ RuleLifecycle    — states: SHADOW → PROMOTED → RETIRED

rl_agent  (PPO reinforcement learning, CPU/memory intensive: 2 CPU / 4 GB limit)
    ├─ PPOAgent         — stable-baselines3 PPO, MlpPolicy, 500k timesteps default
    ├─ TradingEnv       — gymnasium environment
    └─ RewardFunction

rag_memory  (long-term memory)
    ├─ Embedder         — converts trade/context to vectors
    ├─ QdrantManager    — manages Qdrant collections
    └─ MemoryRetriever  — similarity search for relevant past trades

scenario_engine  (crisis scenario backtesting)
    └─ validates strategies against historical crisis events (COVID crash, FTX collapse, etc.)
```

### Infrastructure (all in `docker-compose.yml`)

| Container | Purpose | Port |
|---|---|---|
| `postgres:16` | Rule genomes, trades, drift logs, agent perf, evolution logs, scenario results | 5432 |
| `timescaledb` | Time-series: ticks, order book, klines, crypto_metrics, feature store | 5433 |
| `redis:7` | Inter-service pub/sub, real-time state, 2 GB LRU cache | 6379 |
| `qdrant` | Vector DB for RAG memory and autopsy embeddings | 6333/6334 |
| `prometheus_monitor` | Metrics scraping | 9090 |
| `grafana` | Dashboards | 3001 |
| `dashboard` | Next.js trading UI | 3000 |

**Kafka removed:** All services previously had `kafka-python` dependencies. These have been replaced with Redis pub/sub and direct Redis key writes. `kafka-python` is no longer in any `requirements.txt` and there is no Kafka service in `docker-compose.yml`.

### PostgreSQL Schema (database: `prometheus_trading`)

Key tables:
- `rule_genomes` — NEAT genome DNA, lifecycle status (`TRIAL → APPROVED → ACTIVE → PROBATION → DEAD → ARCHIVED`), fitness metrics
- `trades` — all trade records with regime, drift, confidence, agent votes, shadow flag
- `drift_logs` — concept drift events (ADWIN/DDM scores, KL divergence, affected features)
- `agent_performance` — per-agent accuracy tracked by regime
- `evolution_logs` — NEAT generation events
- `scenario_results` — crisis scenario test outcomes
- `system_health` — service health checks

### TimescaleDB Schema (database: `prometheus_timeseries`)

Hypertables with automatic compression: `market_ticks`, `order_book_snapshots`, `klines`, `crypto_metrics`, `features`. The `klines_1h` materialized view continuously aggregates 1m candles.

## Key Design Conventions

### Agent system
All 9 agents follow the same interface: `analyze(context: dict) -> dict` returning `{agent: str, response: str}`. Each agent calls the Claude API with `claude-sonnet-4-6`. The `DebateAgent` calls `debate(bull, bear, context)` and returns `{agent: "debate_agent", verdict: str}` where the verdict is JSON with `direction`, `confidence`, `consensus_reasoning`, `dissent_risk`.

### Signal confidence threshold
`SignalGenerator` suppresses signals to `"flat"` when the confidence-weighted vote falls below 0.60. Do not lower this threshold without testing shadow performance.

### Immunity system
`services/immunity_system/immunity.py` is marked `# IMMUTABLE — DO NOT MODIFY WITHOUT SECURITY REVIEW`. The hard limits (`MAX_POSITION_PCT=0.05`, `MAX_DAILY_LOSS_PCT=0.02`, `MAX_LEVERAGE=3.0`, `MAX_OPEN_POSITIONS=3`) are not configurable at runtime.

### Shadow promotion criteria
Defined in `services/shadow_system/promotion_engine.py`: 100 trades, Sharpe ≥ 1.5, win rate ≥ 52%, max drawdown < 10%. These are the gates before any strategy touches live capital.

### Service entrypoints
Most `main.py` files are scaffolds (`asyncio.sleep(3600)`) — the real logic lives in the sibling modules. When implementing a service, wire up those modules in `main.py` rather than adding logic there directly.

### Feature naming
Features written to the TimescaleDB `features` table must match the column names exactly (see `infrastructure/timescale/init.sql` lines 117–158). The feature store is the single source of truth consumed by the signal pipeline.
