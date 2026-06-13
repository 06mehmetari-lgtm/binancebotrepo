#!/usr/bin/env bash
# Tum Python servislerine guncel kodu docker cp ile yukler (build yok).
set -euo pipefail

PROM_DIR="${PROMETHEUS_DIR:-/root/prometheus}"
cd "$PROM_DIR"

live_cp() {
  local src="$1" container="$2"
  if [ ! -d "$src" ]; then
    echo "  ATLA (yok): $src"
    return 0
  fi
  if ! docker ps --format '{{.Names}}' | grep -qx "$container"; then
    echo "  ATLA (calismiyor): $container"
    return 0
  fi
  docker cp "$src/." "$container:/app/" 2>/dev/null && echo "  OK  $container <- ${src##*/}"
}

copy_shared() {
  local container="$1"
  shift
  if ! docker ps --format '{{.Names}}' | grep -qx "$container"; then
    return 0
  fi
  for f in "$@"; do
    [ -f "services/shared/$f" ] && docker cp "services/shared/$f" "$container:/app/$f" 2>/dev/null || true
  done
}

echo "=== Canli kod yukleme (docker cp) ==="

# Bagimsiz context servisleri
for pair in \
  "services/data_ingestion:prometheus_data" \
  "services/sentiment:prometheus_sentiment" \
  "services/macro:prometheus_macro" \
  "services/feature_engine:prometheus_features" \
  "services/context_engine:prometheus_context" \
  "services/learning_engine:prometheus_learning" \
  "services/neat_evolution:prometheus_neat" \
  "services/rl_agent:prometheus_rl" \
  "services/autopsy:prometheus_autopsy" \
  "services/rag_memory:prometheus_rag" \
  "services/scenario_engine:prometheus_scenarios" \
  "services/backtest:prometheus_backtest" \
  "services/agent_system:prometheus_agents" \
  "services/signal_engine:prometheus_signal" \
  "services/immunity_system:prometheus_immunity" \
  "services/oms:prometheus_oms" \
  "services/shadow_system:prometheus_shadow"; do
  src="${pair%%:*}"
  ctr="${pair##*:}"
  live_cp "$src" "$ctr"
done

# OMS ek modul
[ -f services/oms/portfolio_sync.py ] && \
  docker cp services/oms/portfolio_sync.py prometheus_oms:/app/portfolio_sync.py 2>/dev/null && \
  echo "  OK  prometheus_oms <- portfolio_sync.py" || true

# Shadow OMS modulu
[ -f services/oms/portfolio_sync.py ] && \
  docker cp services/oms/portfolio_sync.py prometheus_shadow:/app/portfolio_sync.py 2>/dev/null && \
  echo "  OK  prometheus_shadow <- portfolio_sync.py" || true

SHARED_COMMON="profit_rules.py risk_limits.py portfolio_try.py"
SHARED_AGENTS="llm_providers.py groq_orchestrator.py llm_status.py llm_runtime_keys.py llm_health.py proxy_pool.py position_plan.py"

for ctr in prometheus_shadow prometheus_oms prometheus_agents prometheus_signal prometheus_immunity; do
  copy_shared "$ctr" $SHARED_COMMON
done
copy_shared prometheus_agents $SHARED_AGENTS

echo "=== Canli kod tamam ==="
