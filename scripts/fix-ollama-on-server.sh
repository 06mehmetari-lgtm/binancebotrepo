#!/usr/bin/env bash
# Groq/Cerebras 1010 (Cloudflare IP engeli) sonrası yerel Ollama'yı tek LLM kaynağı yap.
# Sunucuda: bash scripts/fix-ollama-on-server.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env}"
MODEL="${OLLAMA_PULL_MODEL:-llama3.2:3b}"

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

echo "══ Ollama fallback (VPS IP → Groq/Cerebras 1010 engelli) ══"
upsert LLM_PROVIDER_ORDER "ollama,groq,cerebras,sambanova,openrouter,mistral,together,fireworks,cohere,deepseek,huggingface,google,perplexity,zai,anthropic"
upsert OLLAMA_MODEL "$MODEL"
upsert OLLAMA_TIMEOUT "240"
upsert OLLAMA_URL "http://ollama:11434"

grep -E '^(LLM_PROVIDER_ORDER|OLLAMA_MODEL|OLLAMA_TIMEOUT)=' "$ENV_FILE"

if ! docker inspect prometheus_ollama >/dev/null 2>&1; then
  echo "Starting ollama ..."
  docker compose up -d ollama
  sleep 3
fi

echo ""
echo "── Ollama API (host) ──"
if curl -sf --max-time 8 http://127.0.0.1:11434/api/tags >/tmp/ollama_tags.json; then
  python3 - <<'PY' /tmp/ollama_tags.json
import json, sys
d = json.load(open(sys.argv[1]))
models = [m.get("name") for m in d.get("models") or []]
print("  yüklü modeller:", ", ".join(models) if models else "(boş — pull gerekli)")
PY
else
  echo "  ! Ollama /api/tags yanıt vermedi"
fi

echo ""
echo "── Model pull: $MODEL (ilk seferde 2–10 dk sürebilir) ──"
docker compose exec -T ollama ollama pull "$MODEL"

echo ""
echo "── Warmup (kısa inference) ──"
docker compose exec -T ollama ollama run "$MODEL" "Reply OK" --verbose=false 2>&1 | tail -3 || true

echo ""
echo "Recreating agent_system + learning_engine with Ollama-first order ..."
docker compose up -d --force-recreate agent_system learning_engine

echo ""
echo "Probe:"
echo "  docker cp scripts/probe-llm-keys.py prometheus_agents:/tmp/probe_llm_keys.py"
echo "  docker compose exec agent_system python3 /tmp/probe_llm_keys.py"
echo ""
echo "Not: Groq/Cerebras bu sunucu IP'sinden çalışmaz (Cloudflare 1010)."
echo "     Anahtarlar ev/PC'den test edilebilir; üretimde Ollama veya farklı VPS."
