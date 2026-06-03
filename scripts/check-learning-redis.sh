#!/usr/bin/env bash
# Öğrenme verisi Redis kontrolü — ~/prometheus içinde
set -euo pipefail
cd "$(dirname "$0")/.."

PW=$(grep '^REDIS_PASSWORD=' .env | cut -d= -f2- | tr -d '\r')
if [[ -z "$PW" ]]; then
  echo "REDIS_PASSWORD .env'de yok"
  exit 1
fi

RC="docker compose exec -T redis redis-cli -a $PW --no-auth-warning"

echo "=== Redis PING ==="
$RC PING

echo ""
echo "=== learn:profile sayısı ==="
$RC KEYS 'learn:profile:*' | grep -c 'learn:profile:' || echo 0

echo ""
echo "=== Örnek LABUSDT profili ==="
$RC GET learn:profile:LABUSDT | head -c 800
echo ""

echo ""
echo "=== trade:lessons:LABUSDT (son 2) ==="
$RC LRANGE trade:lessons:LABUSDT 0 1

echo ""
echo "=== learning_engine log (son 5 learn) ==="
docker compose logs learning_engine --tail 80 2>/dev/null | grep '\[learn\]' | tail -5
