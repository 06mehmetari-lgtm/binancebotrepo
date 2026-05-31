#!/bin/bash
# ═══════════════════════════════════════════════════════
# Prometheus Trading System — Tam Sağlık Kontrolü
# Kullanım: bash scripts/system_check.sh
# ═══════════════════════════════════════════════════════

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

OK()   { echo -e "  ${GREEN}✓${NC} $1"; }
FAIL() { echo -e "  ${RED}✗${NC} $1"; }
WARN() { echo -e "  ${YELLOW}⚠${NC} $1"; }
INFO() { echo -e "  ${CYAN}→${NC} $1"; }
HDR()  { echo -e "\n${BOLD}${BLUE}═══ $1 ═══${NC}"; }

echo -e "${BOLD}${CYAN}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║     PROMETHEUS TRADING SYSTEM — SAĞLIK KONTROLÜ      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  Tarih: $(date '+%d/%m/%Y %H:%M:%S')"

# ── 1. GIT / KOD VERSİYONU ─────────────────────────────
HDR "1. KOD VERSİYONU"
BRANCH=$(git branch --show-current 2>/dev/null || echo "bilinmiyor")
LAST_COMMIT=$(git log --oneline -1 2>/dev/null || echo "bilinmiyor")
LOCAL_HASH=$(git rev-parse HEAD 2>/dev/null)
REMOTE_HASH=$(git rev-parse origin/$BRANCH 2>/dev/null)

INFO "Branch: $BRANCH"
INFO "Son commit: $LAST_COMMIT"

if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
  OK "Kod güncel (GitHub ile senkronize)"
else
  WARN "Yerel kod GitHub'dan farklı — 'git pull' gerekebilir"
  INFO "Local:  ${LOCAL_HASH:0:10}"
  INFO "Remote: ${REMOTE_HASH:0:10}"
fi

# Dashboard container'ın hangi build üzerinde çalıştığını kontrol et
DASHBOARD_BUILD=$(docker inspect prometheus_dashboard 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
if d:
    labels = d[0].get('Config', {}).get('Labels', {})
    created = d[0].get('Created', 'bilinmiyor')[:19]
    print(f'Container oluşturulma: {created}')
" 2>/dev/null)
[ -n "$DASHBOARD_BUILD" ] && INFO "$DASHBOARD_BUILD" || WARN "Dashboard container bilgisi alınamadı"

# ── 2. DOCKER CONTAINER DURUMU ─────────────────────────
HDR "2. DOCKER CONTAINER DURUMU"

CONTAINERS=(
  "prometheus_dashboard:Dashboard (Next.js)"
  "prometheus_data:Data Ingestion"
  "prometheus_features:Feature Engine"
  "prometheus_signal:Signal Engine"
  "prometheus_context:Context Engine"
  "prometheus_agents:Agent System (AI)"
  "prometheus_immunity:Immunity System"
  "prometheus_oms:OMS (Order Manager)"
  "prometheus_shadow:Shadow System"
  "prometheus_neat:NEAT Evolution"
  "prometheus_rl:RL Agent"
  "prometheus_sentiment:Sentiment"
  "prometheus_macro:Macro"
  "prometheus_redis:Redis"
  "prometheus_postgres:PostgreSQL"
  "prometheus_timescale:TimescaleDB"
)

RUNNING=0; STOPPED=0
for entry in "${CONTAINERS[@]}"; do
  NAME="${entry%%:*}"
  LABEL="${entry##*:}"
  STATUS=$(docker inspect --format='{{.State.Status}}' "$NAME" 2>/dev/null)
  RESTART=$(docker inspect --format='{{.RestartCount}}' "$NAME" 2>/dev/null)
  if [ "$STATUS" = "running" ]; then
    if [ "$RESTART" -gt 5 ] 2>/dev/null; then
      WARN "$LABEL (restart sayısı: $RESTART — sorun olabilir)"
    else
      OK "$LABEL (running)"
    fi
    RUNNING=$((RUNNING + 1))
  elif [ -z "$STATUS" ]; then
    INFO "$LABEL (yok — başlatılmamış)"
  else
    FAIL "$LABEL ($STATUS)"
    STOPPED=$((STOPPED + 1))
  fi
done
echo ""
INFO "Özet: $RUNNING çalışıyor, $STOPPED durdurulmuş"

# ── 3. REDİS VERİ AKIŞI ────────────────────────────────
HDR "3. REDİS VERİ AKIŞI (Yapay Zeka Çalışıyor mu?)"

REDIS_PASS=$(grep REDIS_PASSWORD .env 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d "'" | tr -d ' ')
if [ -z "$REDIS_PASS" ]; then
  WARN "REDIS_PASSWORD .env'de bulunamadı"
  RC="docker exec prometheus_redis redis-cli"
else
  RC="docker exec prometheus_redis redis-cli -a $REDIS_PASS"
fi

# Feature Engine verisi
FEAT_COUNT=$($RC keys "features:latest:*" 2>/dev/null | wc -l | tr -d ' ')
if [ "$FEAT_COUNT" -gt 100 ]; then
  OK "Feature Engine: $FEAT_COUNT coin için özellik hesaplanmış"
elif [ "$FEAT_COUNT" -gt 0 ]; then
  WARN "Feature Engine: sadece $FEAT_COUNT coin (500 bekleniyor, başlıyor olabilir)"
else
  FAIL "Feature Engine: hiç veri yok — servis çalışmıyor!"
fi

# Signal Engine verisi
SIG_COUNT=$($RC keys "signal:latest:*" 2>/dev/null | wc -l | tr -d ' ')
if [ "$SIG_COUNT" -gt 50 ]; then
  OK "Signal Engine: $SIG_COUNT coin için sinyal üretiliyor"
elif [ "$SIG_COUNT" -gt 0 ]; then
  WARN "Signal Engine: $SIG_COUNT sinyal (az, ısınıyor olabilir)"
else
  FAIL "Signal Engine: hiç sinyal yok!"
fi

# Agent System verisi (AI kararları)
AGENT_COUNT=$($RC keys "agents:verdicts:*" 2>/dev/null | wc -l | tr -d ' ')
if [ "$AGENT_COUNT" -gt 20 ]; then
  OK "Agent System (AI): $AGENT_COUNT coin için karar üretilmiş"
elif [ "$AGENT_COUNT" -gt 0 ]; then
  WARN "Agent System: $AGENT_COUNT karar (az, ısınıyor)"
else
  WARN "Agent System: henüz karar yok (Groq key gerekebilir)"
fi

# Context Engine
CTX_COUNT=$($RC keys "context:latest:*" 2>/dev/null | wc -l | tr -d ' ')
if [ "$CTX_COUNT" -gt 50 ]; then
  OK "Context Engine: $CTX_COUNT coin için bağlam analizi yapılıyor"
else
  WARN "Context Engine: $CTX_COUNT bağlam verisi"
fi

# WebSocket bağlantısı
WS_STATUS=$($RC get "ws:status" 2>/dev/null | python3 -c "import sys,json; d=json.loads(sys.stdin.read().strip() or '{}'); print(f\"{d.get('status','?')} - {d.get('symbols',0)} coin\")" 2>/dev/null)
[ -n "$WS_STATUS" ] && OK "WebSocket: $WS_STATUS" || WARN "WebSocket: durum bilgisi yok"

# OMS pozisyonlar
POS_COUNT=$($RC keys "oms:position:*" 2>/dev/null | wc -l | tr -d ' ')
TRADE_COUNT=$($RC llen "oms:trade_history" 2>/dev/null | tr -d ' ')
INFO "Açık pozisyon: $POS_COUNT | Kapatılan işlem: $TRADE_COUNT"

# Shadow system
SHADOW=$($RC get "shadow:leaderboard" 2>/dev/null | python3 -c "
import sys, json
raw = sys.stdin.read().strip()
if not raw: print('veri yok')
else:
    d = json.loads(raw)
    if d: print(f'{len(d)} strateji — en iyi Sharpe: {max(s.get(\"sharpe\",0) for s in d):.3f}')
    else: print('boş')
" 2>/dev/null)
INFO "Shadow leaderboard: $SHADOW"

# Backtest sonuçları
BT_COUNT=$($RC get "backtest:results" 2>/dev/null | python3 -c "
import sys, json
raw = sys.stdin.read().strip()
if not raw: print('yok')
else:
    d = json.loads(raw)
    n = len(d.get('results', {}))
    print(f'{n} sembol backtest sonucu mevcut')
" 2>/dev/null)
INFO "Backtest: $BT_COUNT"

# Fear & Greed
FG=$($RC get "sentiment:fear_greed" 2>/dev/null | python3 -c "
import sys, json
raw = sys.stdin.read().strip()
if raw:
    d = json.loads(raw)
    print(f\"Değer: {d.get('value','?')} — {d.get('classification','?')}\")
else: print('yok')
" 2>/dev/null)
INFO "Fear & Greed: $FG"

# ── 4. YAPAY ZEKA ÖĞRENİYOR MU? ───────────────────────
HDR "4. YAPAY ZEKA ÖĞRENİYOR MU?"

# NEAT Evolution
NEAT_GENOMES=$($RC keys "genome:*" 2>/dev/null | wc -l | tr -d ' ')
NEAT_STATS=$($RC get "neat:stats" 2>/dev/null | python3 -c "
import sys, json
raw = sys.stdin.read().strip()
if raw:
    d = json.loads(raw)
    gen = d.get('generation', 0)
    best = d.get('best_fitness', 0)
    count = d.get('genome_count', 0)
    print(f'Nesil {gen} | En iyi fitness: {best:.4f} | {count} genom')
else: print('henüz başlamadı')
" 2>/dev/null)
INFO "NEAT Evrimi: $NEAT_STATS"

# RL Agent
RL_STATUS=$(docker inspect prometheus_rl --format='{{.State.Status}}' 2>/dev/null)
RL_RESTART=$(docker inspect prometheus_rl --format='{{.RestartCount}}' 2>/dev/null)
[ "$RL_STATUS" = "running" ] && OK "PPO/RL Agent: çalışıyor (restart: $RL_RESTART)" || FAIL "PPO/RL Agent: $RL_STATUS"

# Agent son aktivitesi
LAST_AGENT=$($RC get "agents:last_run" 2>/dev/null)
if [ -n "$LAST_AGENT" ]; then
  SECS=$(python3 -c "import time; print(int(time.time() - $LAST_AGENT))" 2>/dev/null)
  [ "$SECS" -lt 120 ] && OK "Agent System: $SECS saniye önce çalıştı" || WARN "Agent System: ${SECS}s önce (${SECS}s bekleniyor ≤120)"
else
  WARN "Agent System son çalışma zamanı bilinmiyor"
fi

# Drift Detector
DRIFT_STATS=$($RC keys "drift:*" 2>/dev/null | wc -l)
INFO "Drift Detector kayıtları: $DRIFT_STATS"

# ── 5. SERVİS LOGLARI (Son Hatalar) ───────────────────
HDR "5. SERVİS LOG KONTROL (Son 20 Satır)"

SERVICES=("prometheus_signal" "prometheus_agents" "prometheus_features" "prometheus_oms")
for svc in "${SERVICES[@]}"; do
  LABEL=$(echo $svc | sed 's/prometheus_//')
  ERROR_COUNT=$(docker logs --tail=50 "$svc" 2>&1 | grep -c -i "error\|exception\|traceback" || echo 0)
  LAST_LOG=$(docker logs --tail=1 "$svc" 2>&1 | head -1)
  if [ "$ERROR_COUNT" -gt 5 ]; then
    FAIL "$LABEL: $ERROR_COUNT hata son 50 satırda!"
    INFO "Son log: ${LAST_LOG:0:80}"
  else
    OK "$LABEL: $ERROR_COUNT hata (normal)"
  fi
done

# ── 6. DASHBOARD VERSİYON KONTROLÜ ─────────────────────
HDR "6. DASHBOARD KOD GÜNCEL Mİ?"

REPO_COMMIT=$(git log --oneline -1 --format="%H" 2>/dev/null)
CONTAINER_CREATED=$(docker inspect prometheus_dashboard --format='{{.Created}}' 2>/dev/null | cut -c1-19)
GIT_COMMIT_DATE=$(git log -1 --format="%ci" 2>/dev/null | cut -c1-19)

INFO "Son Git commit tarihi: $GIT_COMMIT_DATE"
INFO "Dashboard container oluşturulma: $CONTAINER_CREATED"

# Container'ı yeniden build etmek gerekiyor mu?
if [ -n "$CONTAINER_CREATED" ] && [ -n "$GIT_COMMIT_DATE" ]; then
  # ISO tarihlerini karşılaştır
  if [[ "$CONTAINER_CREATED" < "$GIT_COMMIT_DATE" ]]; then
    WARN "Dashboard container Git'teki son değişikliklerden ÖNCE build edilmiş!"
    echo ""
    echo -e "  ${RED}▶ AKSIYON GEREKLİ:${NC}"
    echo -e "  ${YELLOW}  docker compose pull && git pull && docker compose up -d --build dashboard oms${NC}"
    echo ""
  else
    OK "Dashboard container güncel görünüyor"
  fi
fi

# ── 7. ÖZET VE TAVSİYELER ─────────────────────────────
HDR "7. ÖZET"

echo ""
if [ "$FEAT_COUNT" -gt 100 ] && [ "$SIG_COUNT" -gt 50 ]; then
  echo -e "  ${GREEN}${BOLD}✓ SİSTEM AKTİF — Veri akıyor, sinyal üretiliyor${NC}"
else
  echo -e "  ${RED}${BOLD}✗ SİSTEM SORUNU — Veri akışında problem var${NC}"
fi

echo ""
echo -e "  ${BOLD}Önerilen komutlar:${NC}"
echo -e "  ${CYAN}• Güncel kod al + dashboard yeniden build:${NC}"
echo -e "    git pull && docker compose up -d --build dashboard oms"
echo ""
echo -e "  ${CYAN}• Tüm servisleri yeniden başlat:${NC}"
echo -e "    docker compose up -d --build"
echo ""
echo -e "  ${CYAN}• Canlı log izleme:${NC}"
echo -e "    docker compose logs -f signal_engine agent_system feature_engine"
echo ""
echo -e "  ${CYAN}• Redis'te veri kontrolü:${NC}"
echo -e "    docker exec prometheus_redis redis-cli -a \$REDIS_PASSWORD keys 'signal:latest:*' | wc -l"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
