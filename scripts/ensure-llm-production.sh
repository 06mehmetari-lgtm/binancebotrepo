#!/usr/bin/env bash
# Tek komut: LLM'nin bu VPS'te kesin çalışması (Ollama birincil; Groq/Cerebras 1010 bypass).
# Sunucuda: cd ~/prometheus && bash scripts/ensure-llm-production.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env}"
MODEL="${OLLAMA_PULL_MODEL:-llama3.2:3b}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
ok() { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; exit 1; }

[[ -f "$ENV_FILE" ]] || fail "$ENV_FILE yok"

upsert() {
  local key="$1" val="$2"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >>"$ENV_FILE"
  fi
}

echo "════════════════════════════════════════"
echo " ENSURE LLM — Ollama production mode"
echo "════════════════════════════════════════"

# 1) .env — yerel LLM zorunlu (Cloudflare 1010 VPS)
upsert LLM_PROVIDER_ORDER "ollama"
upsert LLM_OLLAMA_ONLY "true"
upsert LLM_CLOUD_BLOCKED "true"
upsert OLLAMA_MODEL "$MODEL"
upsert OLLAMA_TIMEOUT "300"
upsert OLLAMA_URL "http://ollama:11434"
upsert AI_ENABLE_SWARM "false"
upsert AGENT_CONCURRENCY "6"
upsert GUARD_DEBATE_CONCURRENCY "1"
upsert LEARNING_CONCURRENCY "4"
upsert GROQ_LEARN_MODEL "llama-3.3-70b-versatile"
upsert CEREBRAS_MODEL "gpt-oss-120b"

ok ".env güncellendi (Ollama-only + düşük concurrency)"

# 2) Ollama
docker compose up -d ollama
echo "Ollama başlatılıyor (healthcheck)..."
for i in $(seq 1 30); do
  if docker inspect --format='{{.State.Health.Status}}' prometheus_ollama 2>/dev/null | grep -q healthy; then
    ok "Ollama healthy"
    break
  fi
  if curl -sf --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    ok "Ollama API yanıt veriyor"
    break
  fi
  sleep 3
  [[ "$i" -eq 30 ]] && warn "Ollama henüz hazır değil — pull devam edecek"
done

echo "Model pull: $MODEL (2–15 dk sürebilir)..."
docker compose exec -T ollama ollama pull "$MODEL"

echo "Warmup inference..."
docker compose exec -T ollama ollama run "$MODEL" "Say OK" 2>&1 | tail -5 || warn "warmup yavaş — ilk agent isteği uzun sürebilir"

# 3) Rebuild agents (llm_providers: Ollama önce, cloud skip)
echo ""
echo "Docker rebuild agent_system + learning_engine..."
docker compose build agent_system learning_engine
docker compose up -d --force-recreate ollama agent_system learning_engine

sleep 5

# 4) Probe
if [[ -f scripts/probe-llm-keys.py ]]; then
  docker cp scripts/probe-llm-keys.py prometheus_agents:/tmp/probe_llm_keys.py 2>/dev/null || true
  echo ""
  echo "── Probe ──"
  docker compose exec -T agent_system python3 /tmp/probe_llm_keys.py 2>&1 || true
  if docker compose exec -T agent_system python3 /tmp/probe_llm_keys.py 2>&1 | grep -q 'OK   response='; then
    ok "Ollama OK — sistem LLM kullanabilir"
  else
    warn "Ollama probe OK değil — RAM kontrol: en az 6GB boş (free -h)"
    warn "Alternatif model: OLLAMA_PULL_MODEL=tinyllama bash scripts/ensure-llm-production.sh"
  fi
fi

echo ""
echo "════════════════════════════════════════"
ok "Tamamlandı. Agent log:"
echo "  docker compose logs agent_system --tail 20 | grep -i ollama"
echo ""
echo "Groq/Cerebras bu IP'den çalışmaz (1010). İleride proxy:"
echo "  HTTPS_PROXY=http://user:pass@host:port + LLM_OLLAMA_ONLY=false"
echo "════════════════════════════════════════"
