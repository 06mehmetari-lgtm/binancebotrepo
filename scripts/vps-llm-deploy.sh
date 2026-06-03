#!/usr/bin/env bash
# VPS: tek script, satir satir — traceback'i terminale YAPISTIRMAYIN.
# Kullanim: cd ~/prometheus && bash scripts/vps-llm-deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== 1) Git dosyalari ==="
git fetch origin 2>/dev/null || true
git checkout origin/master -- \
  services/shared/llm_providers.py \
  services/shared/groq_orchestrator.py \
  services/shared/proxy_pool.py \
  services/agent_system/debate_agent.py \
  services/agent_system/Dockerfile \
  services/learning_engine/Dockerfile \
  scripts/setup-vps-llm-wait-mode.sh \
  scripts/probe-llm-keys.py \
  scripts/vps-llm-deploy.sh \
  docker-compose.yml 2>/dev/null || true

echo "=== 2) .env (Groq acik, cloud block kapali) ==="
upsert() {
  local k="$1" v="$2"
  if grep -qE "^${k}=" .env 2>/dev/null; then
    sed -i "s|^${k}=.*|${k}=${v}|" .env
  else
    echo "${k}=${v}" >>.env
  fi
}
upsert ALLOW_GROQ_ON_VPS true
upsert LLM_CLOUD_BLOCKED false
upsert LLM_OLLAMA_ONLY false
upsert LLM_PROVIDER_ORDER "google,groq,cerebras,ollama"
grep -E '^(ALLOW_GROQ|LLM_CLOUD|LLM_PROVIDER_ORDER|GOOGLE_AI_API_KEY)=' .env | head -5

echo "=== 3) Ollama + build ==="
docker compose up -d ollama
docker compose build agent_system learning_engine

echo "=== 4) Restart agents ==="
docker compose up -d --force-recreate agent_system learning_engine
sleep 6

echo "=== 5) Probe (dosyadan — kopyala yapistir degil) ==="
docker cp scripts/probe-llm-keys.py prometheus_agents:/tmp/probe_llm_keys.py
docker compose exec -T agent_system python3 /tmp/probe_llm_keys.py

echo ""
echo "=== 6) Hizli LLM test ==="
docker compose exec -T agent_system python3 /tmp/probe_llm_keys.py 2>/dev/null | tail -20 || true
docker compose exec -T agent_system python3 -c "import sys;sys.path.insert(0,'/app');from llm_providers import provider_order,chat_completion;print('order',provider_order());t,l=chat_completion('Say OK',max_tokens=8,temperature=0);print('result',l,(t or '')[:40])"

echo ""
echo "=== Bitti. Log: docker compose logs agent_system --tail 30 | grep LLM ==="
