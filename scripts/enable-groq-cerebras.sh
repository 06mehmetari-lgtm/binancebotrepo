#!/usr/bin/env bash
# Groq + Cerebras'ı VPS'te çalıştır (1010 bypass).
# Yöntem 1 — Residential proxy (.env):
#   HTTPS_PROXY=http://user:pass@host:port
# Yöntem 2 — LLM relay (ev PC / farklı sunucu, bkz. scripts/run-llm-relay-at-home.md):
#   LLM_RELAY_URL=https://xxxx.trycloudflare.com
#   LLM_RELAY_SECRET=uzun-rastgele-sifre
#
# Sunucuda: bash scripts/enable-groq-cerebras.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env}"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }

upsert() {
  local key="$1" val="$2"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >>"$ENV_FILE"
  fi
}

has_proxy=false
has_relay=false
grep -qE '^HTTPS_PROXY=.+' "$ENV_FILE" 2>/dev/null && has_proxy=true
grep -qE '^HTTP_PROXY=.+' "$ENV_FILE" 2>/dev/null && has_proxy=true
grep -qE '^ALL_PROXY=socks' "$ENV_FILE" 2>/dev/null && has_proxy=true
grep -qE '^LLM_RELAY_URL=https?://' "$ENV_FILE" 2>/dev/null && has_relay=true

if ! $has_proxy && ! $has_relay; then
  echo "════════════════════════════════════════════════════════"
  echo " Groq/Cerebras bu VPS IP'sinden doğrudan ÇALIŞMAZ (1010)."
  echo " Aşağıdakilerden BİRİNİ .env dosyasına ekleyin, sonra tekrar çalıştırın:"
  echo ""
  echo " 1) Residential proxy (Webshare, IPRoyal, Bright Data vb.):"
  echo "    HTTPS_PROXY=http://USER:PASS@proxy-host:PORT"
  echo ""
  echo " 2) Ev PC relay + Cloudflare Tunnel (ücretsiz):"
  echo "    LLM_RELAY_URL=https://xxxx.trycloudflare.com"
  echo "    LLM_RELAY_SECRET=rastgele-uzun-sifre"
  echo "    (Kurulum: scripts/run-llm-relay-at-home.md)"
  echo "════════════════════════════════════════════════════════"
  exit 1
fi

echo "Cloud LLM bypass algılandı — Groq/Cerebras etkinleştiriliyor..."
upsert LLM_OLLAMA_ONLY "false"
upsert LLM_CLOUD_BLOCKED "false"
upsert LLM_PROVIDER_ORDER "groq,cerebras,ollama"
upsert AI_ENABLE_SWARM "false"

grep -E '^(HTTPS_PROXY|HTTP_PROXY|ALL_PROXY|LLM_RELAY_URL|LLM_RELAY_SECRET|LLM_PROVIDER_ORDER)=' "$ENV_FILE" \
  | sed 's/\(SECRET\|PASS\|PASSWORD\)=.*/\1=***MASKED***/; s/PROXY=.*/PROXY=***MASKED***/'

echo ""
echo "Rebuild + restart agents..."
docker compose build agent_system learning_engine
docker compose up -d --force-recreate agent_system learning_engine

sleep 4
if [[ -f scripts/probe-llm-keys.py ]]; then
  docker cp scripts/probe-llm-keys.py prometheus_agents:/tmp/probe_llm_keys.py 2>/dev/null || true
  echo ""
  echo "── Probe ──"
  out=$(docker compose exec -T agent_system python3 /tmp/probe_llm_keys.py 2>&1) || true
  echo "$out"
  if echo "$out" | grep -qE '^\s+OK\s+GROQ'; then
    echo "✓ Groq çalışıyor"
  else
    echo "✗ Groq hâlâ fail — proxy/relay URL veya kimlik bilgisi kontrol edin"
  fi
  if echo "$out" | grep -qE '^\s+OK\s+CEREBRAS'; then
    echo "✓ Cerebras çalışıyor"
  fi
fi
