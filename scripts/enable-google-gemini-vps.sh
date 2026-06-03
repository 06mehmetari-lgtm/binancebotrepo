#!/usr/bin/env bash
# PC kapalı — VPS'ten Google Gemini (Groq yerine, çoğu VPS'te 1010 yok).
# Anahtar: https://aistudio.google.com/apikey → GOOGLE_AI_API_KEY
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env}"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }

if ! grep -qE '^GOOGLE_AI_API_KEY=.' "$ENV_FILE" 2>/dev/null; then
  echo "GOOGLE_AI_API_KEY yok. https://aistudio.google.com/apikey → .env ekleyin"
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

echo "Gemini (Google API) öncelikli — VPS 7/24, PC gerekmez"
upsert LLM_PROVIDER_ORDER "google,ollama,groq,cerebras"
upsert GOOGLE_AI_MODEL "gemini-2.0-flash"
upsert LLM_OLLAMA_ONLY "false"
upsert LLM_CLOUD_BLOCKED "false"
upsert AI_ENABLE_SWARM "false"

docker compose build agent_system learning_engine
docker compose up -d --force-recreate agent_system learning_engine

sleep 3
docker cp scripts/probe-llm-keys.py prometheus_agents:/tmp/probe_llm_keys.py 2>/dev/null || true
docker compose exec -T agent_system python3 -c "
import sys; sys.path.insert(0,'/app')
from llm_providers import collect_keys, _try_openai_provider
keys = collect_keys('GOOGLE_AI_API_KEY', 'GEMINI_API_KEY')
print('google keys:', len(keys))
t,l = _try_openai_provider('google', 'Reply OK', 16, 0, None)
print('OK', l, (t or '')[:40] if t else 'FAIL')
" 2>&1

echo "Log: docker compose logs agent_system --tail 20 | grep -i google"
