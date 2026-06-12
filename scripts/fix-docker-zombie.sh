#!/usr/bin/env bash
# Zombie container / "cannot stop container PID is zombie" — Docker daemon kurtarma
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== 1) Hangi container takılı? ==="
docker ps -a --format 'table {{.ID}}\t{{.Names}}\t{{.Status}}' | head -40

ZOMBIE_ID="${1:-}"
if [ -z "$ZOMBIE_ID" ]; then
  ZOMBIE_ID=$(docker ps -aq --filter "status=dead" 2>/dev/null | head -1 || true)
fi

echo ""
echo "=== 2) Compose down (zaman aşımı kısa) ==="
docker compose down --timeout 10 2>/dev/null || true

echo ""
echo "=== 3) Takılı container'ları zorla kaldır ==="
for id in $(docker ps -aq 2>/dev/null); do
  docker rm -f "$id" 2>/dev/null || true
done

if [ -n "$ZOMBIE_ID" ]; then
  docker rm -f "$ZOMBIE_ID" 2>/dev/null || true
fi

echo ""
echo "=== 4) Docker daemon yenile (root gerekir) ==="
if command -v systemctl >/dev/null 2>&1; then
  systemctl restart docker || service docker restart || true
  sleep 5
fi

echo ""
echo "=== 5) Altyapı önce ==="
docker compose up -d redis postgres timescaledb qdrant
sleep 8
docker compose up -d ollama data_ingestion feature_engine context_engine
sleep 5
docker compose up -d agent_system signal_engine learning_engine shadow_system oms immunity_system dashboard
sleep 3
docker compose up -d

echo ""
echo "=== 6) Durum ==="
docker compose ps

PW=$(grep '^REDIS_PASSWORD=' .env 2>/dev/null | cut -d= -f2- | tr -d '\r' || true)
if [ -n "$PW" ]; then
  docker compose exec -T redis redis-cli -a "$PW" --no-auth-warning PING || true
fi

echo ""
echo "API test:"
curl -sf -o /dev/null -w "positions %{http_code}\n" --max-time 15 http://localhost:3000/api/positions || echo "positions fail"
curl -sf -o /dev/null -w "learning %{http_code}\n" --max-time 25 "http://localhost:3000/api/learning?symbol=BTCUSDT" || echo "learning fail"
