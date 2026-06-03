#!/usr/bin/env bash
# Prometheus — tam üretim deploy (dashboard + AI pipeline)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Prometheus production deploy ==="
export REDIS_PASSWORD="${REDIS_PASSWORD:-$(grep '^REDIS_PASSWORD=' .env 2>/dev/null | cut -d= -f2-)}"

SERVICES=(
  dashboard
  agent_system
  shadow_system
  learning_engine
  signal_engine
  feature_engine
  context_engine
  oms
)

echo "Building (no-cache)..."
docker compose build --no-cache "${SERVICES[@]}"

echo "Recreating containers..."
docker compose up -d --force-recreate "${SERVICES[@]}"

sleep 12
echo ""
echo "=== Health check ==="
bash check.sh 2>/dev/null || true

echo ""
echo "Dashboard: http://$(hostname -I 2>/dev/null | awk '{print $1}'):3000"
echo "  /learning  /analiz  /system  /chat  /positions"
