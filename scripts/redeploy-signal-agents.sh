#!/usr/bin/env bash
# Force-deploy signal_engine + agent_system fixes (no stale Docker COPY cache).
set -euo pipefail
cd "$(dirname "$0")/.."

export REDIS_PASSWORD="${REDIS_PASSWORD:-$(grep '^REDIS_PASSWORD=' .env 2>/dev/null | cut -d= -f2-)}"

echo "==> Git sync"
git fetch origin
git reset --hard origin/master
echo "HEAD: $(git rev-parse --short HEAD)"

echo "==> Source check (must show list bracket after sum)"
grep -A6 'total_w = sum' services/signal_engine/ensemble.py | head -8
grep -q '_vote_signal' services/agent_system/explanation_builder.py \
  && echo "OK: explanation_builder has _vote_signal helpers"

echo "==> Rebuild without cache"
docker compose build --no-cache signal_engine agent_system

echo "==> Restart"
docker compose up -d --force-recreate signal_engine agent_system

sleep 45

echo "==> In-container verify"
docker exec prometheus_signal python -c "
from ensemble import fuse_sources
d,c,s,_ = fuse_sources('long', 0.7, 'short', 0.5, None, 0)
print('ensemble OK', d, c)
"
docker exec prometheus_agents python -c "
from explanation_builder import _vote_signal
from debate_agent import AgentVote
v = AgentVote('technical', 'long', 0.6, {})
print('agent OK', _vote_signal(v))
"

echo "==> Logs (should have NO sum() / AgentVote.get errors)"
docker compose logs signal_engine --tail 20 2>&1 | grep -E 'ERROR|ensemble OK' || true
docker compose logs agent_system --tail 20 2>&1 | grep -E 'ERROR|agent OK' || true

bash check.sh
