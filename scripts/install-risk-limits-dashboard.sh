#!/usr/bin/env bash
# Sunucuda: risk limit formu + API dosyalarını origin/master'dan çeker ve dashboard'u yeniden derler.
# Kullanım (~/prometheus içinde):
#   cp .env /tmp/.env.bak && bash scripts/install-risk-limits-dashboard.sh && cp /tmp/.env.bak .env

set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> fetch origin/master"
git fetch origin master

FILES=(
  services/dashboard/package.json
  services/dashboard/package-lock.json
  services/dashboard/src/app/api/risk-limits/route.ts
  services/dashboard/src/app/api/risk/route.ts
  services/dashboard/src/app/risk/page.tsx
  services/dashboard/src/app/positions/page.tsx
  services/dashboard/src/components/RiskLimitsEditor.tsx
  services/dashboard/src/lib/postgres.ts
  services/dashboard/src/lib/risk-limits-config.ts
  services/dashboard/src/lib/risk-limits-service.ts
)

for f in "${FILES[@]}"; do
  echo "    checkout $f"
  git checkout origin/master -- "$f"
done

echo "==> build dashboard"
docker compose build --no-cache dashboard
docker compose up -d --force-recreate dashboard

sleep 3
echo "==> API test"
curl -sf http://127.0.0.1:3000/api/risk-limits | head -c 200 || echo "WARN: API JSON dönmedi — log: docker compose logs dashboard --tail 30"

echo "==> Redis sync (Postgres -> Redis)"
bash scripts/sync-risk-limits-redis.sh 2>/dev/null || true

echo "OK. Tarayıcı: /positions veya /risk — turuncu 'Dinamik risk limitleri' paneli + input alanları"
