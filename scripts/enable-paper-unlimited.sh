#!/usr/bin/env bash
# Sanal para — sınırsız paper trading limitleri (Postgres + Redis)
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-prometheus}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-changeme}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
REDIS_PASSWORD="${REDIS_PASSWORD:?REDIS_PASSWORD .env içinde tanımlı değil}"

echo "==> Postgres risk limits (paper agresif)"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d prometheus_trading <<'SQL'
INSERT INTO system_risk_limits (
  id, max_leverage, max_position_pct, max_daily_loss_pct, max_open_positions,
  min_signal_confidence, min_immunity_confidence, max_trades_per_day, updated_by
) VALUES (1, 10, 1.0, 1.0, 500, 0.35, 0.30, 10000, 'enable-paper-unlimited')
ON CONFLICT (id) DO UPDATE SET
  max_leverage = EXCLUDED.max_leverage,
  max_position_pct = EXCLUDED.max_position_pct,
  max_daily_loss_pct = EXCLUDED.max_daily_loss_pct,
  max_open_positions = EXCLUDED.max_open_positions,
  min_signal_confidence = EXCLUDED.min_signal_confidence,
  min_immunity_confidence = EXCLUDED.min_immunity_confidence,
  max_trades_per_day = EXCLUDED.max_trades_per_day,
  updated_by = EXCLUDED.updated_by,
  updated_at = NOW();
SQL

PAYLOAD='{"max_leverage":10,"max_position_pct":1.0,"max_daily_loss_pct":1.0,"max_open_positions":500,"min_signal_confidence":0.35,"min_immunity_confidence":0.30,"max_trades_per_day":10000,"updated_at":'$(date +%s)',"updated_by":"enable-paper-unlimited"}'

echo "==> Redis cache sync"
docker compose exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning SET "system:risk_limits:v1" "$PAYLOAD" >/dev/null
docker compose exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning PUBLISH "ch:risk_limits:updated" "$PAYLOAD" >/dev/null

echo "==> Restart trading pipeline"
docker compose restart signal_engine oms agent_system immunity_system shadow_system

echo "Done. PAPER_UNLIMITED=true ve DRY_RUN=true ile 500 coin / sınırsız günlük işlem aktif."
