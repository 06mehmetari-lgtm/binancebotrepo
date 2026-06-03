#!/usr/bin/env bash
# PC kapalı, ev IP yok — Gemini (limit olunca bekler) + Ollama yedek. Groq/Cerebras atlanır.
# Sunucuda: bash scripts/setup-vps-llm-wait-mode.sh
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

echo "════════════════════════════════════════"
echo " VPS LLM — PC yok, limit beklemeli mod"
echo "════════════════════════════════════════"

upsert LLM_VPS_MODE "true"
upsert ALLOW_GROQ_ON_VPS "true"
upsert LLM_PROVIDER_ORDER "google,groq,cerebras,ollama"
upsert LLM_OLLAMA_ONLY "false"
upsert LLM_CLOUD_BLOCKED "false"
upsert LLM_QUOTA_WAIT_SEC "45"
upsert GOOGLE_AI_MODEL "gemini-2.0-flash"
upsert OLLAMA_MODEL "llama3.2:3b"
upsert OLLAMA_TIMEOUT "300"
upsert AI_ENABLE_SWARM "false"
upsert AGENT_CONCURRENCY "6"
upsert GUARD_DEBATE_CONCURRENCY "1"
upsert LEARNING_CONCURRENCY "4"

if ! grep -qE '^GOOGLE_AI_API_KEY=.' "$ENV_FILE" 2>/dev/null; then
  echo ""
  echo "⚠ GOOGLE_AI_API_KEY yok — sadece Ollama kullanılacak."
  echo "  Ücretsiz anahtar: https://aistudio.google.com/apikey"
  echo "  .env: GOOGLE_AI_API_KEY=AIza..."
  echo "  Sonra bu scripti tekrar çalıştırın."
  upsert LLM_PROVIDER_ORDER "ollama"
fi

echo ""
grep -E '^(LLM_VPS_MODE|LLM_PROVIDER_ORDER|LLM_QUOTA_WAIT|GOOGLE_AI_API_KEY|OLLAMA_MODEL)=' "$ENV_FILE" \
  | sed 's/GOOGLE_AI_API_KEY=.*/GOOGLE_AI_API_KEY=***MASKED***/'

echo ""
echo "Ollama model pull..."
docker compose up -d ollama
docker compose exec -T ollama ollama pull "${OLLAMA_PULL_MODEL:-llama3.2:3b}" || true

echo ""
echo "Rebuild agent_system + learning_engine..."
docker compose build agent_system learning_engine
docker compose up -d --force-recreate agent_system learning_engine

sleep 5
echo ""
echo "Test (agent container):"
docker compose exec -T agent_system python3 -c "
import sys; sys.path.insert(0,'/app')
from llm_providers import vps_llm_mode, provider_order, chat_completion
print('VPS mode:', vps_llm_mode())
print('order:', provider_order())
t,l = chat_completion('Reply one word: OK', max_tokens=12, temperature=0)
print('LLM:', l or 'none', (t or '')[:50] if t else 'FAIL→ rule agents still run')
" 2>&1 || true

echo ""
echo "════════════════════════════════════════"
echo " Tamam. Limit dolunca log: kota/limit — bekleniyor"
echo " Groq/Cerebras DENENİR (ALLOW_GROQ_ON_VPS=true, otomatik 1010 skip yok)."
echo " 403 + network settings = gerçek CF engeli (logda HTTP body görünür)."
echo " Token/kota açılınca sıradaki sağlayıcı devam eder."
echo "════════════════════════════════════════"
