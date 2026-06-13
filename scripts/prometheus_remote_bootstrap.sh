#!/usr/bin/env bash
# Prometheus — tam sunucu bootstrap (VPS'te çalışır)
# PROMETHEUS_AYAGA_KALDIR.bat bu scripti yükleyip çalıştırır.
set -euo pipefail

PROM_DIR="${PROMETHEUS_DIR:-/root/prometheus}"
LOG="/tmp/prometheus_bootstrap.log"
BUILD_LOG="/tmp/prometheus_build.log"
MODE="${DEPLOY_MODE:-quick}"          # quick | full | skip | minimal
NO_CACHE="${BUILD_NO_CACHE:-0}"      # 1 = docker build --no-cache

exec > >(tee -a "$LOG") 2>&1
echo "=============================================="
echo " Prometheus bootstrap — $(date -Iseconds)"
echo " DIR=$PROM_DIR MODE=$MODE"
echo "=============================================="

cd "$PROM_DIR" || { echo "HATA: $PROM_DIR yok"; exit 1; }

# ── 1) Git ─────────────────────────────────────
echo "=== [1/10] Git ==="
if [ -d .git ]; then
  if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
    git stash push -u -m "bootstrap-$(date +%Y%m%d-%H%M)" 2>/dev/null || true
  fi
  git fetch origin master 2>/dev/null || git fetch origin 2>/dev/null || true
  git pull origin master || git pull || true
  git log -1 --oneline || true
else
  echo "UYARI: .git yok — mevcut dosyalarla devam"
fi

# ── 2) .env ────────────────────────────────────
echo "=== [2/10] .env ==="
if [ ! -f .env ]; then
  if [ -f .env.bak ]; then
    cp .env.bak .env
    echo "OK: .env.bak'tan geri yüklendi"
  else
    cp .env.example .env
    echo "UYARI: .env.example kopyalandı — şifreleri kontrol edin"
  fi
fi
cp .env .env.bak 2>/dev/null || true

upsert_env() {
  local k="$1" v="$2"
  if grep -q "^${k}=" .env 2>/dev/null; then
    sed -i "s|^${k}=.*|${k}=${v}|" .env
  else
    echo "${k}=${v}" >> .env
  fi
}

upsert_env DRY_RUN true
upsert_env PORTFOLIO_TRY 10000
upsert_env TRADE_FEE_PCT_PER_SIDE 0.001
upsert_env RECOVERY_DCA_MAX_TIERS 3
upsert_env RECOVERY_MAX_SYMBOL_PCT 0.15
upsert_env RISK_PER_TRADE_PCT 0.01
upsert_env RISK_MAX_DAILY_LOSS_PCT 0.03
upsert_env RISK_MAX_WEEKLY_LOSS_PCT 0.08
upsert_env RISK_MAX_ATR_PCT 5.0
upsert_env BACKTEST_WALK_FORWARD true
upsert_env PAPER_UNLIMITED true
upsert_env PAPER_MIN_HOLD_SEC 180
upsert_env GUARD_PROFIT_TIERS "1.5,3,6,12"
upsert_env GUARD_TAKE_PROFIT_PCT 1.2
upsert_env GUARD_MAX_LOSS_PCT 1.0
upsert_env GUARD_EMERGENCY_LOSS_PCT 1.8
upsert_env GUARD_TRAIL_MIN_PEAK 2.0
upsert_env GUARD_TRAIL_GIVEBACK_PCT 0.5
upsert_env GUARD_PROFIT_PROTECT_PCT 0.8
upsert_env SHADOW_MIN_CONFIDENCE 0.62
upsert_env SHADOW_MAX_OPEN 30
upsert_env SHADOW_HARD_STOP_PCT 1.2
upsert_env SYMBOL_COOLDOWN_SEC 1800
upsert_env PAPER_MIN_SIGNAL_CONFIDENCE 0.58
upsert_env OMS_MIN_CONFIDENCE 0.60
upsert_env PAPER_TAKE_PROFIT_PCT 1.5
upsert_env PAPER_STOP_LOSS_PCT 1.2
upsert_env LLM_PROVIDER_ORDER "openrouter,ollama,google,groq,cerebras"
upsert_env LLM_VPS_MODE true
upsert_env ALLOW_GROQ_ON_VPS true
upsert_env SIGNAL_MIN_CONFIDENCE 0.60
upsert_env LEARNING_FAST_TRACK true

if [ -n "${OPENROUTER_API_KEY:-}" ]; then
  export OPENROUTER_API_KEY
  python3 <<'PYENV'
import os, re
from pathlib import Path
v = os.environ.get("OPENROUTER_API_KEY", "")
if not v:
    raise SystemExit(0)
p = Path(".env")
text = p.read_text()
pat = re.compile(r"^OPENROUTER_API_KEY=.*$", re.M)
line = "OPENROUTER_API_KEY=" + v
text = pat.sub(line, text) if pat.search(text) else text.rstrip() + "\n" + line + "\n"
p.write_text(text)
print("env: OPENROUTER_API_KEY ok")
PYENV
fi

set -a
# shellcheck disable=SC1091
source .env
set +a
REDIS_PW="${REDIS_PASSWORD:?REDIS_PASSWORD .env içinde yok}"

# ── 3) Altyapı ───────────────────────────────
echo "=== [3/10] Altyapı (redis, postgres, timescale, qdrant, ollama) ==="
docker compose up -d redis postgres timescaledb qdrant ollama 2>&1 | tail -15
sleep 8
docker compose exec -T redis redis-cli -a "$REDIS_PW" --no-auth-warning PING

# ── 4) Build (PARALEL — skip modunda atlanir) ─
BUILD_SERVICES_FULL=(
  data_ingestion sentiment macro feature_engine context_engine
  agent_system signal_engine learning_engine shadow_system oms immunity_system
  dashboard backtest autopsy rag_memory neat_evolution rl_agent scenario_engine
)
BUILD_SERVICES_QUICK=(
  data_ingestion context_engine feature_engine signal_engine agent_system learning_engine
  shadow_system oms immunity_system dashboard
)
BUILD_SERVICES_MINIMAL=(
  shadow_system agent_system signal_engine oms
)

CACHE_FLAG=""
[ "$NO_CACHE" = "1" ] && CACHE_FLAG="--no-cache"

echo "build start $(date -Iseconds) mode=$MODE" > "$BUILD_LOG"
BUILD_EXIT=0

if [ "$MODE" = "skip" ]; then
  echo "=== [4/10] BUILD ATLANDI (skip) — mevcut image + git pull ==="
  echo "SKIP_BUILD" >> "$BUILD_LOG"
else
  if [ "$MODE" = "quick" ]; then
    BUILD_LIST=("${BUILD_SERVICES_QUICK[@]}")
  elif [ "$MODE" = "minimal" ]; then
    BUILD_LIST=("${BUILD_SERVICES_MINIMAL[@]}")
  else
    BUILD_LIST=("${BUILD_SERVICES_FULL[@]}")
  fi
  TOTAL=${#BUILD_LIST[@]}
  echo "=== [4/10] Docker PARALEL build: $TOTAL servis (tek komut, ~8-20 dk) ==="
  echo "Mod=$MODE servisler=${BUILD_LIST[*]}" >> "$BUILD_LOG"
  set +e
  # Paralel build — sirayla 17x yerine tek seferde (cok daha hizli)
  docker compose build --parallel --progress=plain $CACHE_FLAG "${BUILD_LIST[@]}" 2>&1 | tee -a "$BUILD_LOG"
  BUILD_EXIT=${PIPESTATUS[0]}
  set -e
  if [ "$BUILD_EXIT" -ne 0 ]; then
    echo "UYARI: paralel build exit $BUILD_EXIT — kritik servisler tek tek deneniyor..."
    for svc in "${BUILD_LIST[@]}"; do
      echo ">>> retry $svc"
      docker compose build $CACHE_FLAG "$svc" 2>&1 | tail -5 >> "$BUILD_LOG" || true
    done
  else
    echo "OK: paralel build tamam ($TOTAL servis)"
  fi
  echo "BUILD_EXIT:$BUILD_EXIT" >> "$BUILD_LOG"
fi

# ── 5) Paper / risk scriptleri ─────────────────
if [ "$MODE" = "skip" ]; then
  echo "=== [5/10] Paper + risk (SKIP — rebuild yok, sadece redis + restart) ==="
  chmod +x scripts/*.sh 2>/dev/null || true
  ./scripts/enable-paper-unlimited.sh 2>/dev/null || true
  ./scripts/sync-risk-limits-redis.sh 2>/dev/null || true
else
  echo "=== [5/10] Paper + risk limitleri ==="
  chmod +x scripts/*.sh 2>/dev/null || true
  ./scripts/patch-paper-hold.sh 2>/dev/null || true
  ./scripts/enable-paper-unlimited.sh 2>/dev/null || true
  ./scripts/sync-risk-limits-redis.sh 2>/dev/null || true
fi

# ── 6) Tüm servisleri başlat ───────────────────
echo "=== [6/10] Servisleri başlat ==="
if [ "$MODE" = "skip" ]; then
  docker compose up -d --no-recreate 2>&1 | tail -15
else
  docker compose up -d \
    data_ingestion sentiment macro feature_engine context_engine \
    agent_system signal_engine learning_engine shadow_system oms immunity_system \
    dashboard backtest autopsy rag_memory neat_evolution rl_agent scenario_engine \
    prometheus_monitor grafana 2>&1 | tail -25
fi
sleep 12

# ── 7) Redis: LLM + portföy ────────────────────
echo "=== [7/10] Redis yapılandırma ==="
python3 <<'PYEOF'
import json, os, subprocess, sys
from pathlib import Path

prom = Path(os.environ.get("PROMETHEUS_DIR", "/root/prometheus"))
env = {}
for line in (prom / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

rp = env.get("REDIS_PASSWORD")
if not rp:
    sys.exit("REDIS_PASSWORD yok")

def rc(*args):
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "redis", "redis-cli", "-a", rp, "--no-auth-warning", *args],
        cwd=str(prom), capture_output=True, text=True,
    )

or_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
if or_key:
    r = rc("GET", "system:llm:key_overrides")
    raw = (r.stdout or "").strip()
    data = json.loads(raw) if raw and raw != "(nil)" else {}
    if not isinstance(data, dict):
        data = {}
    data["openrouter"] = [or_key]
    payload = json.dumps(data)
    rc("SET", "system:llm:key_overrides", payload)
    rc("PUBLISH", "ch:llm:keys_updated", "1")
    print("redis: openrouter key ok")

# 10k TRY portföy seed (yoksa)
r = rc("GET", "portfolio:try:v1")
if not (r.stdout or "").strip() or r.stdout.strip() == "(nil)":
    seed = json.dumps({
        "cap_try": float(env.get("PORTFOLIO_TRY", "10000")),
        "cap_usd": 0,
        "usdt_try": 0,
        "fee_per_side": float(env.get("TRADE_FEE_PCT_PER_SIDE", "0.001")),
        "updated_at": __import__("time").time(),
        "source": "bootstrap",
    })
    rc("SET", "portfolio:try:v1", seed)
    print("redis: portfolio:try:v1 seeded")
else:
    print("redis: portfolio:try:v1 mevcut")

rc("PUBLISH", "ch:portfolio:updated", "1")
print("redis ok")
PYEOF

# ── 8) Zombie + restarting fix ─────────────────
# fix-docker-zombie: tum container siler + docker daemon restart — sadece FIX_DOCKER_ZOMBIE=1
light_health_fix() {
  for c in $(docker compose ps -a --format '{{.Name}}' 2>/dev/null); do
    st=$(docker inspect --format '{{.State.Status}}' "$c" 2>/dev/null || echo unknown)
    if [ "$st" = "restarting" ] || [ "$st" = "exited" ]; then
      echo "  restart $c ($st)"
      docker restart "$c" 2>/dev/null || docker compose up -d "$c" 2>/dev/null || true
    fi
  done
  sleep 3
  docker compose up -d 2>&1 | tail -5 || true
}

if [ "${FIX_DOCKER_ZOMBIE:-0}" = "1" ]; then
  echo "=== [8/10] Container saglik duzeltme (FIX_DOCKER_ZOMBIE=1) ==="
  bash scripts/fix-docker-zombie.sh 2>/dev/null || true
  light_health_fix
else
  echo "=== [8/10] Hafif saglik (exited/restarting restart, docker down YOK) ==="
  light_health_fix
fi

# ── 9) Sağlık kontrolü ─────────────────────────
echo "=== [9/10] Sağlık kontrolü ==="
docker compose ps --format "table {{.Name}}\t{{.Status}}" | head -30

echo ""
echo "--- Pipeline heartbeat ---"
NOW=$(date +%s)
for svc in data_ingestion feature_engine context_engine agent_system signal_engine learning_engine oms shadow_system; do
  TS=$(docker compose exec -T redis redis-cli -a "$REDIS_PW" --no-auth-warning GET "system:heartbeat:$svc" 2>/dev/null | tr -d '\r' || echo "")
  if [ -n "$TS" ] && [ "$TS" != "(nil)" ] && [ "$TS" != "0" ]; then
    AGE=$(python3 -c "print(int($NOW - float('$TS')))" 2>/dev/null || echo "?")
    echo "  $svc: ${AGE}s önce"
  else
    echo "  $svc: BEKLENİYOR (ilk 2-3 dk normal)"
  fi
done

echo ""
echo "--- Redis veri ---"
FEAT=$(docker compose exec -T redis redis-cli -a "$REDIS_PW" --no-auth-warning KEYS "features:latest:*" 2>/dev/null | wc -l | tr -d ' ')
SIG=$(docker compose exec -T redis redis-cli -a "$REDIS_PW" --no-auth-warning KEYS "signal:latest:*" 2>/dev/null | wc -l | tr -d ' ')
echo "  features:latest:* = $FEAT"
echo "  signal:latest:*   = $SIG"

echo ""
echo "--- Dashboard API ---"
curl -sf -o /dev/null -w "  /api/status     HTTP %{http_code}\n" --max-time 20 http://localhost:3000/api/status || echo "  /api/status FAIL"
curl -sf -o /dev/null -w "  /api/positions  HTTP %{http_code}\n" --max-time 20 http://localhost:3000/api/positions || echo "  /api/positions FAIL"
curl -sf -o /dev/null -w "  /api/signals    HTTP %{http_code}\n" --max-time 20 http://localhost:3000/api/signals || echo "  /api/signals FAIL"
curl -sf -o /dev/null -w "  /api/llm/health HTTP %{http_code}\n" --max-time 25 http://localhost:3000/api/llm/health || echo "  /api/llm/health FAIL"

# ── 10) Özet ───────────────────────────────────
echo ""
echo "=== [10/10] TAMAMLANDI ==="
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "194.163.181.39")
echo ""
echo "  Dashboard : http://${IP}:3000"
echo "  System    : http://${IP}:3000/system"
echo "  Signals   : http://${IP}:3000/signals"
echo "  Positions : http://${IP}:3000/positions"
echo "  LLM Keys  : http://${IP}:3000/llm-keys"
echo ""
echo "  Log: $LOG"
echo "  Build log: $BUILD_LOG"
echo "BOOTSTRAP_DONE"
