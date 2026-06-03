#!/usr/bin/env bash
# LLM / Groq / .env tanı — ~/prometheus içinde: bash scripts/check-llm-env.sh
set -euo pipefail
cd "$(dirname "$0")/.."

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
ok() { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; }

echo "════════════════════════════════════════"
echo " PROMETHEUS — LLM / API key tanı"
echo " $(date -Iseconds 2>/dev/null || date)"
echo " cwd: $(pwd)"
echo "════════════════════════════════════════"

# ── 1) .env dosyası ──
echo ""
echo "── 1) Host .env ──"
if [[ ! -f .env ]]; then
  fail ".env yok — cp .env.example .env ve anahtarları doldurun"
  exit 1
fi
ok ".env mevcut ($(wc -l < .env) satır)"

count_groq() { grep -cE '^GROQ_API_KEY(_[0-9]+)?=.' .env 2>/dev/null || echo 0; }
n_groq=$(count_groq)
n_cerebras=$(grep -cE '^CEREBRAS_API_KEY(_[0-9]+)?=.' .env 2>/dev/null || echo 0)

if [[ "$n_groq" -gt 0 ]]; then
  ok "Groq satırları (dolu): $n_groq"
  grep -E '^GROQ_API_KEY(_[0-9]+)?=' .env | sed 's/=.*/=***MASKED***/' | head -12
else
  fail "Groq anahtarı yok (.env içinde GROQ_API_KEY_1=...)"
fi

if [[ "$n_cerebras" -gt 0 ]]; then
  ok "Cerebras satırları: $n_cerebras"
else
  warn "Cerebras anahtarı yok (opsiyonel)"
fi

# boşluk hatası
if grep -qE '^GROQ_API_KEY_1= ' .env 2>/dev/null; then
  fail "GROQ_API_KEY_1= sonrası BOŞLUK var — düzeltin: GROQ_API_KEY_1=gsk_..."
fi

# ── 2) Compose değişken çözümlemesi ──
echo ""
echo "── 2) Compose \${VAR} (host .env → substitution) ──"
if command -v docker >/dev/null 2>&1; then
  g1=$(docker compose config 2>/dev/null | grep -A2 'GROQ_API_KEY_1:' | head -3 || true)
  if echo "$g1" | grep -q 'gsk_\|GROQ_API_KEY_1: ""'; then
    if echo "$g1" | grep -q 'gsk_'; then
      ok "compose GROQ_API_KEY_1 çözümlendi (değer var)"
    else
      fail "compose GROQ_API_KEY_1 BOŞ — .env aynı klasörde mi?"
    fi
  else
    warn "compose config grep (manuel kontrol):"
    docker compose config 2>/dev/null | grep 'GROQ_API_KEY' | head -5 || fail "docker compose config hata"
  fi
else
  warn "docker yok — atlanıyor"
fi

# ── 3) Konteynerler ──
echo ""
echo "── 3) Konteyner durumu ──"
for c in prometheus_agents prometheus_learning prometheus_dashboard prometheus_ollama prometheus_redis; do
  st=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo "missing")
  if [[ "$st" == "running" ]]; then ok "$c: running"
  else fail "$c: $st"
  fi
done

# ── 4) Konteyner içi env (ilk 12 karakter) ──
echo ""
echo "── 4) Konteyner env (prefix only) ──"
peek_env() {
  local c=$1 var=$2
  v=$(docker exec "$c" printenv "$var" 2>/dev/null || true)
  if [[ -n "$v" ]]; then ok "$c $var=${v:0:12}..."
  else fail "$c $var=BOŞ"
  fi
}
peek_env prometheus_agents GROQ_API_KEY_1
peek_env prometheus_learning GROQ_API_KEY_1
peek_env prometheus_dashboard GROQ_API_KEY_1
docker exec prometheus_dashboard printenv OLLAMA_URL 2>/dev/null | grep -q ollama && ok "dashboard OLLAMA_URL set" || warn "dashboard OLLAMA_URL?"

# ── 5) Redis system:llm:status ──
echo ""
echo "── 5) Redis system:llm:status ──"
if [[ -f .env ]]; then
  REDIS_PASSWORD=$(grep '^REDIS_PASSWORD=' .env | cut -d= -f2- | tr -d '\r')
fi
if [[ -z "${REDIS_PASSWORD:-}" ]]; then
  fail "REDIS_PASSWORD .env'de yok"
else
  raw=$(docker exec prometheus_redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning GET system:llm:status 2>/dev/null || true)
  if [[ -z "$raw" || "$raw" == "(nil)" ]]; then
    fail "Redis key yok — agent_system/learning_engine yayınlamıyor"
  else
    ok "Redis key var ($(echo -n "$raw" | wc -c) byte)"
    echo "$raw" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    p=d.get('providers',[])
    g=next((x for x in p if x.get('id')=='groq'),{})
    print('  groq configured:', g.get('configured'), 'keys:', g.get('key_count'), 'env:', g.get('env'))
    print('  any_configured:', d.get('any_configured'))
    pools=d.get('groq_pools',[])
    if pools:
        print('  pools:', ', '.join(f\"{x.get('id')}:{x.get('count')}\" for x in pools[:6]))
except Exception as e:
    print('  JSON parse:', e)
" 2>/dev/null || echo "  (python3 yok — ham): ${raw:0:200}..."
  fi
fi

# ── 6) Son loglar ──
echo ""
echo "── 6) agent_system log (LLM / hata) ──"
docker compose logs agent_system --tail 40 2>/dev/null | grep -iE 'llm|groq|error|exception|status redis|failed' || warn "eşleşen log yok — tam log:"
docker compose logs agent_system --tail 15 2>/dev/null || true

echo ""
echo "── 7) learning_engine log ──"
docker compose logs learning_engine --tail 25 2>/dev/null | grep -iE 'llm|groq|error|exception' || docker compose logs learning_engine --tail 10 2>/dev/null || true

echo ""
echo "── 8) dashboard log ──"
docker compose logs dashboard --tail 20 2>/dev/null || true

echo ""
echo "── 9) API test (dashboard içinden) ──"
code=$(curl -s -o /tmp/learning.json -w '%{http_code}' --max-time 10 http://127.0.0.1:3000/api/learning 2>/dev/null || echo "000")
if [[ "$code" == "200" ]]; then
  ok "GET /api/learning HTTP 200"
  python3 -c "
import json
d=json.load(open('/tmp/learning.json'))
llm=d.get('llm',{})
print('  status_source:', llm.get('status_source'))
print('  groq keys:', llm.get('groq',{}).get('key_count'))
print('  any_configured:', llm.get('any_configured'))
for p in (llm.get('providers') or [])[:4]:
    print(' ', p.get('id'), '✓' if p.get('configured') else '✗', p.get('key_count',0))
" 2>/dev/null || cat /tmp/learning.json | head -c 400
else
  fail "GET /api/learning HTTP $code"
fi

# ── 10) Canlı API ping (Groq + Cerebras) ──
echo ""
echo "── 10) Canlı API testi (her anahtar) ──"
if docker inspect prometheus_agents >/dev/null 2>&1 && [[ -f scripts/probe-llm-keys.py ]]; then
  docker cp scripts/probe-llm-keys.py prometheus_agents:/tmp/probe_llm_keys.py 2>/dev/null || true
  if probe_out=$(docker compose exec -T agent_system python3 /tmp/probe_llm_keys.py 2>&1); then
    echo "$probe_out"
    if echo "$probe_out" | grep -qE '^\s+OK'; then
      ok "probe: en az bir anahtar OK"
    elif echo "$probe_out" | grep -qi 'access denied\|network settings'; then
      fail "probe: Groq 403 — VPS/datacenter IP engeli olabilir (anahtarlar doğru olsa bile)"
      warn "Çözüm: LLM_PROVIDER_ORDER=ollama,groq,... veya farklı sunucu bölgesi"
    elif echo "$probe_out" | grep -qE 'error code: 1010|code: 1010'; then
      fail "probe: Cloudflare 1010 — VPS IP engeli (Groq/Cerebras bu sunucudan çalışmaz)"
      warn "Çözüm: bash scripts/fix-ollama-on-server.sh"
    elif echo "$probe_out" | grep -qE '^\s+FAIL.*403'; then
      fail "probe: tüm anahtarlar 403 — model fix veya IP engeli; fix-ollama-on-server.sh"
    else
      warn "probe bitti; OK satırı yok — fix-llm-models-on-server.sh çalıştırın"
    fi
  else
    fail "probe hata — logları kontrol edin"
  fi
else
  warn "agent_system çalışmıyor veya probe script yok — atlandı"
  echo "  Manuel: docker cp scripts/probe-llm-keys.py prometheus_agents:/tmp/probe_llm_keys.py"
  echo "         docker compose exec agent_system python3 /tmp/probe_llm_keys.py"
fi

echo ""
echo "════════════════════════════════════════"
echo " Özet: Groq ✓ olması için:"
echo "  1) ~/prometheus/.env dolu"
echo "  2) docker compose up --force-recreate agent_system learning_engine dashboard"
echo "  3) Redis system:llm:status dolu + groq key_count >= 1"
echo "  4) Bölüm 10: her GROQ/CEREBRAS anahtarı için OK (sadece .env değil)"
echo "════════════════════════════════════════"
