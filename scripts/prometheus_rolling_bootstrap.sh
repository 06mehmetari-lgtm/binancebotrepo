#!/usr/bin/env bash
# Rolling deploy — Faz1: git + canli kod + restart (~3-5 dk)
#                  Faz2: arka plan full build (dashboard dahil)
set -euo pipefail

PROM_DIR="${PROMETHEUS_DIR:-/root/prometheus}"
LOG="/tmp/prometheus_rolling.log"

exec > >(tee -a "$LOG") 2>&1
echo "=============================================="
echo " Rolling deploy — $(date -Iseconds)"
echo " DIR=$PROM_DIR"
echo "=============================================="

cd "$PROM_DIR" || { echo "HATA: $PROM_DIR yok"; exit 1; }

# ── 1) Git ─────────────────────────────────────
echo "=== [F1/5] Git pull ==="
if [ -d .git ]; then
  git fetch origin master 2>/dev/null || git fetch origin 2>/dev/null || true
  git pull origin master || git pull || true
  git log -1 --oneline || true
else
  echo "UYARI: .git yok"
fi

# ── 2) .env ────────────────────────────────────
echo "=== [F2/5] .env guncelleme ==="
if [ -f .env ]; then
  upsert() {
    local k="$1" v="$2"
    if grep -q "^${k}=" .env 2>/dev/null; then
      sed -i "s|^${k}=.*|${k}=${v}|" .env
    else
      echo "${k}=${v}" >> .env
    fi
  }
  upsert SHADOW_MIN_CONFIDENCE 0.60
  upsert PAPER_MIN_SIGNAL_CONFIDENCE 0.57
  upsert OMS_MIN_CONFIDENCE 0.58
  upsert SYMBOL_COOLDOWN_SEC 900
  upsert MAX_POSITION_HOLD_SEC 3600
  upsert STALE_VERDICT_HOLD_SEC 1200
  grep -q '^SYMBOL_BLACKLIST=' .env 2>/dev/null || \
    upsert SYMBOL_BLACKLIST "ESPORTSUSDT,GTCUSDT,DEXEUSDT,AIOUSDT,BRUSDT,BEATUSDT,NAORISUSDT"
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# ── 3) Altyapi ayakta mi ───────────────────────
echo "=== [F3/5] Altyapi kontrol ==="
docker compose up -d redis postgres timescaledb qdrant 2>&1 | tail -5
sleep 3
RP="${REDIS_PASSWORD:-}"
[ -n "$RP" ] && docker compose exec -T redis redis-cli -a "$RP" --no-auth-warning PING || true

# ── 4) Canli kod + restart ───────────────────────
echo "=== [F4/5] Canli kod + restart (build YOK) ==="
chmod +x scripts/apply_live_code.sh scripts/background_build_all.sh 2>/dev/null || true
bash scripts/apply_live_code.sh

RESTART_SERVICES=(
  data_ingestion feature_engine context_engine signal_engine agent_system
  shadow_system oms immunity_system sentiment macro learning_engine
  autopsy rag_memory neat_evolution rl_agent scenario_engine backtest
)

echo "=== Restart: ${RESTART_SERVICES[*]} ==="
docker compose restart "${RESTART_SERVICES[@]}" 2>&1 | tail -20

echo "=== Heartbeat bekleniyor (20 sn) ==="
sleep 20
if [ -n "$RP" ]; then
  NOW=$(date +%s)
  for svc in data_ingestion shadow_system agent_system signal_engine oms; do
    TS=$(docker compose exec -T redis redis-cli -a "$RP" --no-auth-warning GET "system:heartbeat:$svc" 2>/dev/null | tr -d '\r')
    if [ -n "$TS" ] && [ "$TS" != "(nil)" ]; then
      AGE=$(python3 -c "print(int($NOW - float('$TS')))" 2>/dev/null || echo "?")
      echo "  $svc OK (${AGE}s)"
    else
      echo "  $svc bekleniyor"
    fi
  done
fi

echo ""
echo "=============================================="
echo " FAZ 1 TAMAM — guncel kod CALISIYOR"
echo " Dashboard: http://$(hostname -I 2>/dev/null | awk '{print $1}'):3000"
echo "=============================================="
echo "ROLLING_PHASE1_DONE"

# ── 5) Arka plan build ─────────────────────────
echo "=== [F5/5] Arka plan build baslatiliyor ==="
bash scripts/background_build_all.sh
echo ""
echo "Arka plan build devam ediyor."
echo "  Durum:  tail -f /tmp/prometheus_bg_build.log"
echo "  Bitti:  grep BG_DONE /tmp/prometheus_bg_build.log"
echo "ROLLING_BOOTSTRAP_DONE"
