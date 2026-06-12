#!/usr/bin/env bash
# Hızlı pipeline teşhisi — sinyal / feature / trade sayıları
set -euo pipefail
cd "$(dirname "$0")/.."
PW=$(grep '^REDIS_PASSWORD=' .env | cut -d= -f2- | tr -d '\r')
RC="docker compose exec -T redis redis-cli -a $PW --no-auth-warning"

echo "=== Redis ==="
$RC PING

echo ""
echo "=== Evren ==="
FEAT=$($RC KEYS "features:latest:*" 2>/dev/null | wc -l | tr -d ' ')
SIG=$($RC KEYS "signal:latest:*" 2>/dev/null | wc -l | tr -d ' ')
echo "features:latest:*  = $FEAT"
echo "signal:latest:*    = $SIG"
$RC GET ws:status 2>/dev/null | head -c 200; echo

echo ""
echo "=== İşlemler ==="
echo "oms:trade_history  = $($RC LLEN oms:trade_history)"
echo "oms:position:*     = $($RC KEYS 'oms:position:*' 2>/dev/null | wc -l | tr -d ' ')"
$RC GET portfolio:state:v1 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('open:', d.get('total_open',0))" 2>/dev/null || true

echo ""
echo "=== Risk limitleri (Redis) ==="
$RC GET system:risk_limits:v1 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "(yok)"

echo ""
echo "=== Heartbeat (son 45s = OK) ==="
NOW=$(date +%s)
for svc in feature_engine signal_engine agent_system learning_engine data_ingestion; do
  TS=$($RC GET "system:heartbeat:$svc" 2>/dev/null || echo 0)
  if [ -n "$TS" ] && [ "$TS" != "0" ]; then
    AGE=$(python3 -c "print(int($NOW - float('$TS')))")
    echo "$svc: ${AGE}s ago"
  else
    echo "$svc: NO HEARTBEAT"
  fi
done

echo ""
echo "=== Son sinyaller (non-flat) ==="
$RC KEYS "signal:latest:*" 2>/dev/null | head -20 | while read -r k; do
  [ -z "$k" ] && continue
  $RC GET "$k" 2>/dev/null | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  if d.get('direction')!='flat' and d.get('is_valid'):
    print(d.get('symbol'), d.get('direction'), 'conf=', round(float(d.get('confidence',0)),3))
except: pass
" 2>/dev/null
done

echo ""
echo "=== Log (son 3 satır) ==="
docker compose logs feature_engine --tail 3 2>/dev/null
docker compose logs signal_engine --tail 3 2>/dev/null
