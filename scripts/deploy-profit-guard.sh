#!/usr/bin/env bash
# Kâr alma + paper hold + dashboard — sunucuda çalıştır
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then set -a; source .env; set +a; fi

grep -q GUARD_PROFIT_TIERS .env 2>/dev/null || cat >> .env <<'ENV'
GUARD_PROFIT_TIERS=0.5,2,5,10,25
GUARD_TRAIL_MIN_PEAK=1.5
GUARD_TRAIL_GIVEBACK_PCT=0.6
GUARD_PROFIT_PROTECT_PCT=0.25
PAPER_MIN_HOLD_SEC=120
PAPER_UNLIMITED=true
ENV

[[ -x scripts/patch-paper-hold.sh ]] && ./scripts/patch-paper-hold.sh || true

docker compose build --no-cache agent_system oms dashboard
docker compose up -d agent_system oms dashboard

echo "Deploy tamam. Dashboard Recent Trades'te çıkış nedeni görünür."
