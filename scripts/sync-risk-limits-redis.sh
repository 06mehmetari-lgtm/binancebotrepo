#!/usr/bin/env bash
# Sync system_risk_limits (Postgres) -> Redis system:risk_limits:v1
# Run from repo root: bash scripts/sync-risk-limits-redis.sh

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found in $(pwd)" >&2
  exit 1
fi

PW=$(grep '^REDIS_PASSWORD=' .env | cut -d= -f2- | tr -d '\r')
PG_USER="${POSTGRES_USER:-prometheus}"

JSON=$(docker compose exec -T postgres psql -U "$PG_USER" -d prometheus_trading -t -A -c "
SELECT row_to_json(t)::text FROM (
  SELECT max_leverage, max_position_pct, max_daily_loss_pct, max_open_positions,
    min_signal_confidence, min_immunity_confidence, max_trades_per_day,
    EXTRACT(EPOCH FROM updated_at) AS updated_at, updated_by
  FROM system_risk_limits WHERE id = 1
) t;
" | tr -d '\r\n')

if [[ -z "$JSON" || "$JSON" == "" ]]; then
  echo "ERROR: system_risk_limits row missing. Create table first." >&2
  exit 1
fi

docker compose exec -T redis redis-cli -a "$PW" SET system:risk_limits:v1 "$JSON" >/dev/null
docker compose exec -T redis redis-cli -a "$PW" PUBLISH ch:risk_limits:updated "$JSON" >/dev/null
echo "Redis synced: system:risk_limits:v1"
echo "$JSON"

docker compose restart immunity_system signal_engine oms shadow_system 2>/dev/null || true
