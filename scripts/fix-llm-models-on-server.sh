#!/usr/bin/env bash
# Sunucuda: bash scripts/fix-llm-models-on-server.sh
# Eski model adları + probe 403 sonrası .env günceller, servisleri yeniden oluşturur.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE"
  exit 1
fi

upsert() {
  local key="$1" val="$2"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >>"$ENV_FILE"
  fi
}

echo "Updating deprecated LLM model IDs in $ENV_FILE ..."
upsert GROQ_LEARN_MODEL "llama-3.3-70b-versatile"
upsert GROQ_DEBATE_MODEL "llama-3.3-70b-versatile"
upsert GROQ_MAIN_MODELS "llama-3.3-70b-versatile"
upsert GROQ_MAIN_MODELS_2 "llama-3.1-8b-instant"
upsert GROQ_FAST_MODELS "llama-3.1-8b-instant"
upsert GROQ_FALLBACK_MODEL "llama-3.1-8b-instant"
upsert GROQ_FINAL_MODEL "llama-3.3-70b-versatile"
upsert GROQ_FINAL_MODEL_2 "llama-3.1-8b-instant"
upsert GROQ_LEARNING_MODELS "llama-3.1-8b-instant"
upsert CEREBRAS_MODEL "gpt-oss-120b"

grep -E '^(GROQ_LEARN_MODEL|GROQ_DEBATE_MODEL|CEREBRAS_MODEL)=' "$ENV_FILE" | head -5

echo ""
echo "Rebuilding agent_system + learning_engine (psycopg2 + llm_providers) ..."
docker compose build agent_system learning_engine
docker compose up -d --force-recreate agent_system learning_engine

echo ""
echo "Re-run probe:"
echo "  bash scripts/check-llm-env.sh"
echo ""
echo "If Groq still 403 with 'Access denied' / network: datacenter IP block."
echo "  Set: LLM_PROVIDER_ORDER=ollama,groq,cerebras,...  (Ollama önce)"
