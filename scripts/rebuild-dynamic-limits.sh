#!/usr/bin/env bash
# Dinamik risk limitleri — tüm trading servislerini doğru Dockerfile ile yeniden derler.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> fetch + checkout Dockerfiles + risk_limits"
git fetch origin master
git checkout origin/master -- \
  docker-compose.yml \
  services/shared/risk_limits.py \
  services/immunity_system/ \
  services/signal_engine/Dockerfile \
  services/signal_engine/main.py \
  services/signal_engine/signal_validator.py \
  services/oms/Dockerfile \
  services/oms/main.py \
  services/shadow_system/ \
  services/agent_system/Dockerfile \
  services/agent_system/main.py \
  services/agent_system/position_guard.py \
  scripts/sync-risk-limits-redis.sh

echo "==> build (no cache)"
docker compose build --no-cache immunity_system signal_engine oms shadow_system agent_system

echo "==> recreate"
docker compose up -d --force-recreate immunity_system signal_engine oms shadow_system agent_system

sleep 8
bash scripts/sync-risk-limits-redis.sh

echo "==> immunity:status (should match Redis limits)"
PW=$(grep '^REDIS_PASSWORD=' .env | cut -d= -f2- | tr -d '\r')
docker compose exec -T redis redis-cli -a "$PW" GET system:risk_limits:v1 | head -c 200
echo ""
docker compose exec -T redis redis-cli -a "$PW" GET immunity:status
echo ""
docker compose logs immunity_system --tail 15
