#!/usr/bin/env bash
# Sunucuda tam deploy: git çakışmasını çöz + tüm trading pipeline + dashboard
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== 1) Git: yerel değişiklikleri stash ==="
if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  git stash push -u -m "server-deploy-$(date +%Y%m%d-%H%M)" || true
fi

echo "=== 2) Git pull ==="
git pull origin master

echo "=== 3) .env (git pull .env silmiş olabilir — stash'ten kurtar) ==="
if [ ! -f .env ]; then
  restored=0
  for i in $(seq 0 5); do
    if git stash list | grep -q "stash@{$i}"; then
      if git show "stash@{$i}:.env" > .env 2>/dev/null && [ -s .env ]; then
        echo "OK: .env stash@{$i} içinden geri yüklendi"
        restored=1
        break
      fi
    fi
  done
  if [ "$restored" -eq 0 ] && [ -f .env.bak ]; then
    cp .env.bak .env
    echo "OK: .env .env.bak dosyasından geri yüklendi"
    restored=1
  fi
  if [ "$restored" -eq 0 ]; then
    cp .env.example .env
    echo "UYARI: .env yoktu — .env.example kopyalandı"
    echo "       BINANCE_API_KEY, REDIS_PASSWORD, POSTGRES_PASSWORD doldurun sonra tekrar çalıştırın"
    exit 1
  fi
fi
# Sonraki deploy için yedek
cp .env .env.bak 2>/dev/null || true
PW=$(grep '^REDIS_PASSWORD=' .env | cut -d= -f2- | tr -d '\r')
if [ -z "$PW" ]; then
  echo "UYARI: REDIS_PASSWORD boş"
fi

echo "=== 4) Paper + kâr guard ayarları ==="
set -a
# shellcheck disable=SC1091
source .env
set +a
grep -q '^PAPER_UNLIMITED=' .env || echo 'PAPER_UNLIMITED=true' >> .env
grep -q '^PAPER_MIN_HOLD_SEC=' .env || echo 'PAPER_MIN_HOLD_SEC=120' >> .env
grep -q '^GUARD_PROFIT_TIERS=' .env || echo 'GUARD_PROFIT_TIERS=0.5,2,5,10,25' >> .env
grep -q '^GUARD_TRAIL_MIN_PEAK=' .env || echo 'GUARD_TRAIL_MIN_PEAK=1.5' >> .env
grep -q '^GUARD_TRAIL_GIVEBACK_PCT=' .env || echo 'GUARD_TRAIL_GIVEBACK_PCT=0.6' >> .env
grep -q '^GUARD_PROFIT_PROTECT_PCT=' .env || echo 'GUARD_PROFIT_PROTECT_PCT=0.25' >> .env
chmod +x scripts/patch-paper-hold.sh scripts/enable-paper-unlimited.sh 2>/dev/null || true
./scripts/patch-paper-hold.sh 2>/dev/null || true
./scripts/enable-paper-unlimited.sh 2>/dev/null || true

echo "=== 5) Docker build (dashboard + pipeline) ==="
docker compose build --no-cache dashboard oms shadow_system signal_engine feature_engine \
  data_ingestion context_engine agent_system learning_engine immunity_system autopsy

echo "=== 6) Zombie container varsa temizle ==="
if ! docker compose up -d --dry-run 2>/dev/null; then
  bash scripts/fix-docker-zombie.sh || true
fi

echo "=== 7) Servisleri başlat ==="
docker compose up -d redis postgres timescaledb qdrant ollama
sleep 5
docker compose up -d data_ingestion feature_engine context_engine sentiment macro \
  agent_system signal_engine learning_engine shadow_system oms immunity_system \
  dashboard

echo "=== 8) Sağlık kontrol ==="
docker compose ps
echo ""
echo "Redis:"
docker compose exec -T redis redis-cli -a "$PW" --no-auth-warning PING || true
echo ""
echo "Dashboard API:"
curl -sf -o /dev/null -w "positions HTTP %{http_code}\n" --max-time 15 http://localhost:3000/api/positions || echo "positions FAIL"
curl -sf -o /dev/null -w "learning HTTP %{http_code}\n" --max-time 25 http://localhost:3000/api/learning?symbol=BTCUSDT || echo "learning FAIL"
echo ""
echo "Bitti. Tarayıcı: http://$(hostname -I | awk '{print $1}'):3000/positions"
