-- Existing DB (from repo root):
--   docker compose exec -T postgres psql -U prometheus -d prometheus_trading -f /migrations/002_system_risk_limits.sql
-- Or without mount: cat infrastructure/postgres/migrations/002_system_risk_limits.sql | docker compose exec -T postgres psql -U prometheus -d prometheus_trading

CREATE TABLE IF NOT EXISTS system_risk_limits (
    id                      SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    max_leverage            DOUBLE PRECISION NOT NULL DEFAULT 3.0,
    max_position_pct        DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    max_daily_loss_pct      DOUBLE PRECISION NOT NULL DEFAULT 0.02,
    max_open_positions      INTEGER NOT NULL DEFAULT 3,
    min_signal_confidence   DOUBLE PRECISION NOT NULL DEFAULT 0.60,
    min_immunity_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.52,
    max_trades_per_day      INTEGER NOT NULL DEFAULT 50,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by              VARCHAR(64) NOT NULL DEFAULT 'system'
);

INSERT INTO system_risk_limits (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;
