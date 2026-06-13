#!/usr/bin/env bash
# Paper mod — DRY_RUN: ogrenme icin acik ama karlilik kurallari korunur
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-prometheus}"
REDIS_PASSWORD="${REDIS_PASSWORD:?REDIS_PASSWORD .env icinde tanimli degil}"

# Karlilik odakli paper limitleri (SHADOW_A autopsy sonrasi)
MAX_LEV="${PAPER_MAX_LEVERAGE:-5}"
MAX_POS="${PAPER_MAX_POSITION_PCT:-0.08}"
MAX_DAILY="${PAPER_MAX_DAILY_LOSS_PCT:-0.05}"
MAX_OPEN="${SHADOW_MAX_OPEN:-30}"
MIN_CONF="${PAPER_MIN_SIGNAL_CONFIDENCE:-0.58}"
MIN_IMM="${OMS_MIN_CONFIDENCE:-0.52}"
MAX_TRADES="${PAPER_MAX_TRADES_PER_DAY:-120}"

echo "==> Postgres risk limits (paper — karlilik korumali)"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d prometheus_trading <<SQL
INSERT INTO system_risk_limits (
  id, max_leverage, max_position_pct, max_daily_loss_pct, max_open_positions,
  min_signal_confidence, min_immunity_confidence, max_trades_per_day, updated_by
) VALUES (1, ${MAX_LEV}, ${MAX_POS}, ${MAX_DAILY}, ${MAX_OPEN},
  ${MIN_CONF}, ${MIN_IMM}, ${MAX_TRADES}, 'enable-paper-profit')
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

PAYLOAD=$(python3 -c "
import json, time
print(json.dumps({
  'max_leverage': float('${MAX_LEV}'),
  'max_position_pct': float('${MAX_POS}'),
  'max_daily_loss_pct': float('${MAX_DAILY}'),
  'max_open_positions': int('${MAX_OPEN}'),
  'min_signal_confidence': float('${MIN_CONF}'),
  'min_immunity_confidence': float('${MIN_IMM}'),
  'max_trades_per_day': int('${MAX_TRADES}'),
  'updated_at': time.time(),
  'updated_by': 'enable-paper-profit',
}))
")

echo "==> Redis cache sync"
docker compose exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning \
  SET "system:risk_limits:v1" "$PAYLOAD" >/dev/null
docker compose exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning \
  PUBLISH "ch:risk_limits:updated" "$PAYLOAD" >/dev/null

echo "==> Pipeline restart"
docker compose restart signal_engine oms agent_system immunity_system shadow_system 2>/dev/null || true

echo "Done. Paper mod: max_open=${MAX_OPEN} min_conf=${MIN_CONF} (karlilik korumali)"
