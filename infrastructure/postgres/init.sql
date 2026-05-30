CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ═══════════════════════════════════════
-- 1. KURAL GENOMU (NEAT DNA)
-- ═══════════════════════════════════════
CREATE TABLE rule_genomes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    genome_id       VARCHAR(50) UNIQUE NOT NULL,
    born_at         TIMESTAMPTZ DEFAULT NOW(),
    generation      INTEGER DEFAULT 1,
    species         VARCHAR(100),
    status          VARCHAR(20) DEFAULT 'TRIAL',
    -- TRIAL → APPROVED → ACTIVE → PROBATION → DEAD → ARCHIVED

    topology_nodes  INTEGER,
    topology_conns  INTEGER,
    topology_json   JSONB,

    regime_fit      JSONB,
    active_features JSONB,

    win_rate        FLOAT DEFAULT 0,
    sharpe_ratio    FLOAT DEFAULT 0,
    max_drawdown    FLOAT DEFAULT 0,
    total_trades    INTEGER DEFAULT 0,
    last_30d_sharpe FLOAT DEFAULT 0,
    decay_rate      FLOAT DEFAULT 0,
    fitness_score   FLOAT DEFAULT 0,

    parent_a        UUID REFERENCES rule_genomes(id),
    parent_b        UUID REFERENCES rule_genomes(id),
    mutations_log   JSONB,

    death_reason    VARCHAR(200),
    archived_at     TIMESTAMPTZ,

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_genomes_status  ON rule_genomes(status);
CREATE INDEX idx_genomes_species ON rule_genomes(species);
CREATE INDEX idx_genomes_sharpe  ON rule_genomes(sharpe_ratio DESC);

-- ═══════════════════════════════════════
-- 2. İŞLEMLER (TRADES)
-- ═══════════════════════════════════════
CREATE TABLE trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id        VARCHAR(50) UNIQUE,
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(10) NOT NULL,

    entry_price     DECIMAL(20, 8),
    exit_price      DECIMAL(20, 8),
    quantity        DECIMAL(20, 8),
    pnl_usdt        DECIMAL(20, 8),
    pnl_pct         FLOAT,
    fee_usdt        DECIMAL(20, 8),

    entry_time      TIMESTAMPTZ,
    exit_time       TIMESTAMPTZ,
    hold_duration   INTERVAL,

    genome_id       UUID REFERENCES rule_genomes(id),
    regime_at_entry VARCHAR(10),
    drift_at_entry  VARCHAR(20),
    crisis_level    INTEGER DEFAULT 0,
    confidence      FLOAT,

    signal_source   VARCHAR(50),
    agents_votes    JSONB,
    kelly_size      FLOAT,

    is_shadow       BOOLEAN DEFAULT FALSE,
    shadow_id       VARCHAR(20),

    autopsy_done    BOOLEAN DEFAULT FALSE,
    autopsy_result  JSONB,

    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trades_symbol ON trades(symbol);
CREATE INDEX idx_trades_entry  ON trades(entry_time DESC);
CREATE INDEX idx_trades_genome ON trades(genome_id);
CREATE INDEX idx_trades_shadow ON trades(is_shadow);

-- ═══════════════════════════════════════
-- 3. KAVRAM KAYMASI LOGLARI
-- ═══════════════════════════════════════
CREATE TABLE drift_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    detected_at     TIMESTAMPTZ DEFAULT NOW(),
    symbol          VARCHAR(20),

    adwin_score     FLOAT,
    ddm_score       FLOAT,
    kl_divergence   FLOAT,

    drift_status    VARCHAR(20),
    previous_status VARCHAR(20),

    affected_features JSONB,
    action_taken    VARCHAR(200),

    resolved_at     TIMESTAMPTZ
);

CREATE INDEX idx_drift_detected ON drift_logs(detected_at DESC);
CREATE INDEX idx_drift_symbol   ON drift_logs(symbol);

-- ═══════════════════════════════════════
-- 4. AJAN PERFORMANS
-- ═══════════════════════════════════════
CREATE TABLE agent_performance (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name      VARCHAR(50) NOT NULL,
    period_start    TIMESTAMPTZ,
    period_end      TIMESTAMPTZ,

    correct_calls   INTEGER DEFAULT 0,
    wrong_calls     INTEGER DEFAULT 0,
    accuracy        FLOAT,

    regime          VARCHAR(10),
    weight          FLOAT DEFAULT 1.0,

    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_agent_perf_name   ON agent_performance(agent_name);
CREATE INDEX idx_agent_perf_regime ON agent_performance(regime);

-- ═══════════════════════════════════════
-- 5. EVRİM LOGLARI
-- ═══════════════════════════════════════
CREATE TABLE evolution_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    logged_at   TIMESTAMPTZ DEFAULT NOW(),
    event_type  VARCHAR(50),
    genome_id   UUID REFERENCES rule_genomes(id),
    generation  INTEGER,
    reason      TEXT,
    metrics     JSONB
);

CREATE INDEX idx_evo_logs_type      ON evolution_logs(event_type);
CREATE INDEX idx_evo_logs_genome    ON evolution_logs(genome_id);
CREATE INDEX idx_evo_logs_logged_at ON evolution_logs(logged_at DESC);

-- ═══════════════════════════════════════
-- 6. KRİZ SENARYOLARI
-- ═══════════════════════════════════════
CREATE TABLE scenario_results (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_at                TIMESTAMPTZ DEFAULT NOW(),
    scenario_id           VARCHAR(10),
    scenario_name         VARCHAR(100),

    portfolio_impact_pct  FLOAT,
    risk_engine_response  VARCHAR(200),
    recovery_time_min     INTEGER,
    passed                BOOLEAN,

    details               JSONB
);

CREATE INDEX idx_scenario_id     ON scenario_results(scenario_id);
CREATE INDEX idx_scenario_run_at ON scenario_results(run_at DESC);

-- ═══════════════════════════════════════
-- 7. SİSTEM SAĞLIK
-- ═══════════════════════════════════════
CREATE TABLE system_health (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    checked_at   TIMESTAMPTZ DEFAULT NOW(),
    service_name VARCHAR(50),
    status       VARCHAR(20),
    latency_ms   FLOAT,
    details      JSONB
);

CREATE INDEX idx_health_service    ON system_health(service_name);
CREATE INDEX idx_health_checked_at ON system_health(checked_at DESC);
CREATE INDEX idx_health_status     ON system_health(status);

-- ═══════════════════════════════════════
-- updated_at otomatik güncelleme trigger
-- ═══════════════════════════════════════
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_rule_genomes_updated_at
    BEFORE UPDATE ON rule_genomes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
