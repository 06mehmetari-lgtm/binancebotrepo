#!/usr/bin/env bash
# Tum servisleri arka planda build eder — on plan islem bitince baslatilir.
set -uo pipefail

PROM_DIR="${PROMETHEUS_DIR:-/root/prometheus}"
LOG="/tmp/prometheus_bg_build.log"
PID_FILE="/tmp/prometheus_bg_build.pid"

cd "$PROM_DIR" || exit 1

if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "UYARI: Onceki arka plan build hala calisiyor (PID $OLD_PID)"
    echo "  Log: tail -f $LOG"
    exit 0
  fi
fi

BUILD_SERVICES=(
  data_ingestion sentiment macro feature_engine context_engine
  agent_system signal_engine learning_engine shadow_system oms immunity_system
  dashboard backtest autopsy rag_memory neat_evolution rl_agent scenario_engine
)

(
  echo "BG_START $(date -Iseconds)" > "$LOG"
  echo "Servisler: ${BUILD_SERVICES[*]}" >> "$LOG"
  set -e
  docker compose build --parallel "${BUILD_SERVICES[@]}" >> "$LOG" 2>&1
  BUILD_EXIT=$?
  echo "BUILD_EXIT:$BUILD_EXIT $(date -Iseconds)" >> "$LOG"
  if [ "$BUILD_EXIT" -eq 0 ]; then
    docker compose up -d \
      data_ingestion sentiment macro feature_engine context_engine \
      agent_system signal_engine learning_engine shadow_system oms immunity_system \
      dashboard backtest autopsy rag_memory neat_evolution rl_agent scenario_engine \
      prometheus_monitor grafana >> "$LOG" 2>&1
    echo "BG_DONE $(date -Iseconds)" >> "$LOG"
  else
    echo "BG_FAILED $(date -Iseconds)" >> "$LOG"
  fi
) &

echo $! > "$PID_FILE"
echo "Arka plan build basladi PID=$(cat $PID_FILE)"
echo "Log: tail -f $LOG"
