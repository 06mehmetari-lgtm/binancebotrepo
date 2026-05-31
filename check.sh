#!/usr/bin/env bash
# ============================================================
# PROMETHEUS SYSTEM HEALTH CHECK
# Çalıştır: bash check.sh
# ============================================================

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; WHITE='\033[1;37m'
GRAY='\033[0;90m'; NC='\033[0m'; BOLD='\033[1m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
info() { echo -e "  ${CYAN}→${NC} $1"; }
hdr()  { echo -e "\n${BOLD}${WHITE}══════ $1 ══════${NC}"; }

# Redis command helper (auto-detects password from .env)
REDIS_PASS=$(grep REDIS_PASSWORD .env 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d "'")
if [ -n "$REDIS_PASS" ]; then
  RC="docker exec prometheus_redis redis-cli -a $REDIS_PASS"
else
  RC="docker exec prometheus_redis redis-cli"
fi

rget()  { $RC GET "$1" 2>/dev/null; }
rexists(){ $RC EXISTS "$1" 2>/dev/null; }
rkeys() { $RC KEYS "$1" 2>/dev/null; }
rlen()  { $RC LLEN "$1" 2>/dev/null; }
rttl()  { $RC TTL "$1" 2>/dev/null; }

echo -e "\n${BOLD}${CYAN}⚡ PROMETHEUS TRADING SYSTEM — HEALTH CHECK${NC}"
echo -e "${GRAY}$(date '+%Y-%m-%d %H:%M:%S')${NC}\n"

# ─── 1. DOCKER CONTAINERS ──────────────────────────────────
hdr "1. DOCKER CONTAINERS"
CONTAINERS=(
  "prometheus_redis:Redis"
  "prometheus_data:Data Ingestion"
  "prometheus_features:Feature Engine"
  "prometheus_context:Context Engine"
  "prometheus_signal:Signal Engine"
  "prometheus_agents:Agent System"
  "prometheus_shadow:Shadow System"
  "prometheus_immunity:Immunity System"
  "prometheus_oms:OMS"
  "prometheus_sentiment:Sentiment"
  "prometheus_macro:Macro"
  "prometheus_neat:NEAT Evolution"
  "prometheus_rl:RL Agent"
  "prometheus_backtest:Backtest"
  "prometheus_dashboard:Dashboard"
  "prometheus_autopsy:Autopsy"
)

for entry in "${CONTAINERS[@]}"; do
  NAME="${entry%%:*}"
  LABEL="${entry##*:}"
  STATUS=$(docker inspect --format='{{.State.Status}}' "$NAME" 2>/dev/null)
  RESTART=$(docker inspect --format='{{.RestartCount}}' "$NAME" 2>/dev/null)
  if [ "$STATUS" = "running" ]; then
    if [ "$RESTART" -gt 3 ] 2>/dev/null; then
      warn "$LABEL ${GRAY}($NAME)${NC} — ${GREEN}RUNNING${NC} ${YELLOW}[RESTART:$RESTART]${NC}"
    else
      ok "$LABEL ${GRAY}($NAME)${NC} — ${GREEN}RUNNING${NC}"
    fi
  elif [ -z "$STATUS" ]; then
    fail "$LABEL ${GRAY}($NAME)${NC} — ${RED}NOT FOUND${NC}"
  else
    fail "$LABEL ${GRAY}($NAME)${NC} — ${RED}${STATUS^^}${NC}"
  fi
done

# ─── 2. REDIS DATA — GERÇEK VERİ VAR MI? ───────────────────
hdr "2. REDIS — GERÇEK VERİ KONTROLÜ"

# Feature keys
FEAT_COUNT=$(rkeys "features:latest:*" | wc -l | tr -d ' ')
if [ "$FEAT_COUNT" -gt 0 ]; then
  ok "Feature Engine: ${GREEN}${FEAT_COUNT} sembol${NC} için özellikler mevcut"
  # Show sample
  SAMPLE_KEY=$(rkeys "features:latest:*" | head -1)
  SAMPLE_SYM="${SAMPLE_KEY##*:}"
  TTL=$(rttl "$SAMPLE_KEY")
  info "Örnek: $SAMPLE_SYM (TTL: ${TTL}s kaldı)"
else
  fail "Feature Engine: ${RED}Hiç veri yok${NC} — data_ingestion veya feature_engine çalışmıyor"
fi

# Signal keys
SIG_COUNT=$(rkeys "signal:latest:*" | wc -l | tr -d ' ')
if [ "$SIG_COUNT" -gt 0 ]; then
  LONG_C=$(rkeys "signal:latest:*" | xargs -I{} sh -c "docker exec prometheus_redis redis-cli ${REDIS_PASS:+-a $REDIS_PASS} GET '{}' 2>/dev/null" | grep -c '"long"' 2>/dev/null || echo 0)
  SHORT_C=$(rkeys "signal:latest:*" | xargs -I{} sh -c "docker exec prometheus_redis redis-cli ${REDIS_PASS:+-a $REDIS_PASS} GET '{}' 2>/dev/null" | grep -c '"short"' 2>/dev/null || echo 0)
  ok "Signal Engine: ${GREEN}${SIG_COUNT} sinyal${NC} mevcut ${GRAY}(long:$LONG_C short:$SHORT_C)${NC}"
else
  fail "Signal Engine: ${RED}Hiç sinyal yok${NC} — features olmadan çalışamaz"
fi

# Context keys
CTX_COUNT=$(rkeys "context:latest:*" | wc -l | tr -d ' ')
if [ "$CTX_COUNT" -gt 0 ]; then
  ok "Context Engine: ${GREEN}${CTX_COUNT} sembol${NC} için bağlam mevcut"
else
  warn "Context Engine: ${YELLOW}Veri yok${NC} — regime/crisis tespiti çalışmıyor"
fi

# Agent keys
AGT_COUNT=$(rkeys "agents:verdict:*" | wc -l | tr -d ' ')
if [ "$AGT_COUNT" -gt 0 ]; then
  ok "Agent System: ${GREEN}${AGT_COUNT} sembol${NC} için yapay zeka kararı mevcut"
  # Show a sample verdict
  SAMPLE_AGT=$(rkeys "agents:verdict:*" | head -1)
  SAMPLE_AGT_SYM="${SAMPLE_AGT##*:}"
  VERDICT=$(rget "$SAMPLE_AGT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('direction','?'), d.get('confidence','?'))" 2>/dev/null)
  info "Örnek: $SAMPLE_AGT_SYM → $VERDICT"
else
  warn "Agent System: ${YELLOW}Kararlar yok${NC} — Groq/Ollama bağlantısı kontrol edilmeli"
fi

# Shadow leaderboard
SHADOW=$(rget "shadow:leaderboard")
if [ -n "$SHADOW" ]; then
  TRADES=$(echo "$SHADOW" | python3 -c "import sys,json; d=json.load(sys.stdin); print(sum(e.get('trades',0) for e in d))" 2>/dev/null)
  BEST_S=$(echo "$SHADOW" | python3 -c "import sys,json; d=json.load(sys.stdin); e=d[0] if d else {}; print(f\"{e.get('shadow_id','?')} Sharpe={e.get('sharpe',0):.2f} WR={e.get('win_rate',0):.1%}\")" 2>/dev/null)
  ok "Shadow System: ${GREEN}Çalışıyor${NC} — Toplam ${TRADES} işlem | En iyi: $BEST_S"
else
  warn "Shadow System: ${YELLOW}Leaderboard yok${NC}"
fi

# Immunity status
IMMU=$(rget "immunity:status")
if [ -n "$IMMU" ]; then
  HALTED=$(echo "$IMMU" | python3 -c "import sys,json; d=json.load(sys.stdin); print('DURDU' if d.get('system_halted') else 'AKTİF')" 2>/dev/null)
  DTRADES=$(echo "$IMMU" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('daily_trades',0))" 2>/dev/null)
  DL=$(echo "$IMMU" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('daily_loss_pct',0))" 2>/dev/null)
  ok "Immunity System: ${GREEN}$HALTED${NC} — Günlük: $DTRADES işlem, %$DL kayıp"
else
  warn "Immunity System: ${YELLOW}Durum yazılmıyor${NC} — container yeni dağıtım gerekiyor"
fi

# OMS positions
OMS_COUNT=$(rkeys "oms:position:*" | wc -l | tr -d ' ')
DAILY_PNL=$(rget "oms:daily_pnl")
if [ "$OMS_COUNT" -gt 0 ] || [ -n "$DAILY_PNL" ]; then
  ok "OMS: ${GREEN}${OMS_COUNT} açık pozisyon${NC} | Günlük PnL: \$${DAILY_PNL:-0}"
else
  info "OMS: Açık pozisyon yok (normal — shadow'dan önce gelir)"
fi

# Backtest
BT_STATUS=$(rget "backtest:status")
BT_RESULTS=$(rexists "backtest:results")
if [ "$BT_RESULTS" = "1" ]; then
  BT_INFO=$(rget "backtest:results" | python3 -c "
import sys,json
d=json.load(sys.stdin)
s=d.get('summary',{})
print(f\"WR={s.get('avg_win_rate_pct',0):.1f}%  Sharpe={s.get('portfolio_sharpe',0):.2f}  Getiri={s.get('avg_return_pct',0):+.1f}%  ({s.get('symbols_tested',0)} sembol)\")
" 2>/dev/null)
  ok "Backtest: ${GREEN}Sonuçlar mevcut${NC} — $BT_INFO"
elif [ -n "$BT_STATUS" ]; then
  BT_PROG=$(echo "$BT_STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d.get('status','?')} {d.get('completed',0)}/{d.get('total','?')}\")" 2>/dev/null)
  warn "Backtest: ${YELLOW}Çalışıyor${NC} — $BT_PROG"
else
  warn "Backtest: ${YELLOW}Sonuç yok${NC} — container başlatılmalı"
fi

# ─── 3. AKTİVİTE AKIŞI ─────────────────────────────────────
hdr "3. SON AKTİVİTE (Son 10 Olay)"
ACTIVITY_LEN=$(rlen "activity:feed")
if [ "$ACTIVITY_LEN" -gt 0 ]; then
  ok "${GREEN}${ACTIVITY_LEN} olay${NC} activity:feed listesinde"
  $RC LRANGE "activity:feed" 0 9 2>/dev/null | python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        d = json.loads(line)
        t = d.get('type','?')
        sym = d.get('symbol','')
        ts = d.get('time', 0)
        import datetime
        dt = datetime.datetime.fromtimestamp(ts).strftime('%H:%M:%S') if ts else '??:??:??'
        if t == 'scan_summary':
            print(f'  {dt}  scan_summary  total={d.get(\"total\",0)} long={d.get(\"long\",0)} short={d.get(\"short\",0)}')
        elif t == 'signal':
            print(f'  {dt}  signal  {sym}  {d.get(\"direction\",\"?\").upper()}  conf={d.get(\"confidence\",0):.2f}')
        elif t == 'rsi_alert':
            print(f'  {dt}  rsi_alert  {sym}  RSI={d.get(\"rsi\",\"?\")}  {d.get(\"label\",\"\")}')
        elif t == 'regime_change':
            print(f'  {dt}  regime_change  {sym}  {d.get(\"prev_regime\",\"?\")} → {d.get(\"regime\",\"?\")}')
        else:
            print(f'  {dt}  {t}  {sym}')
    except:
        pass
" 2>/dev/null
else
  fail "Activity feed boş — signal_engine veya context_engine veri üretmiyor"
fi

# ─── 4. SİNYAL ÖRNEĞİ ──────────────────────────────────────
hdr "4. ÖRNEK SİNYAL (BTC + ETH)"
for SYM in BTCUSDT ETHUSDT; do
  RAW=$(rget "signal:latest:$SYM")
  if [ -n "$RAW" ]; then
    echo "$RAW" | python3 -c "
import sys, json
d = json.load(sys.stdin)
src = d.get('source','?')
dir = d.get('direction','?').upper()
conf = d.get('confidence',0)
rsi = d.get('rsi','?')
regime = d.get('regime','?')
valid = '✓' if d.get('is_valid') else '✗ ('+d.get('reject_reason','?')+')'
print(f'  $SYM → {dir}  conf={conf:.2f}  RSI={rsi}  regime={regime}  valid={valid}  src={src}')
" 2>/dev/null
  else
    echo -e "  ${RED}✗${NC} $SYM — sinyal yok"
  fi
done

# ─── 5. AGENT ÖRNEK ─────────────────────────────────────────
hdr "5. YAPAY ZEKA KARAR ÖRNEĞİ (BTC)"
RAW=$(rget "agents:verdict:BTCUSDT")
if [ -n "$RAW" ]; then
  echo "$RAW" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'  Yön: {d.get(\"direction\",\"?\").upper()}')
print(f'  Güven: {d.get(\"confidence\",0):.2f}')
cs = d.get('consensus_strength', d.get('consensus', '?'))
print(f'  Konsensüs: {cs}')
r = d.get('consensus_reasoning', d.get('reasoning', ''))
if r:
    print(f'  Gerekçe: {str(r)[:120]}...')
" 2>/dev/null
else
  echo -e "  ${YELLOW}⚠${NC}  BTCUSDT için ajan kararı yok"
fi

# ─── 6. CONTAINER LOG (SON HATALAR) ─────────────────────────
hdr "6. CONTAINER HATALAR (Son 5)"
for C in prometheus_signal prometheus_features prometheus_backtest; do
  ERRORS=$(docker logs "$C" --since=30m 2>&1 | grep -i "error\|exception\|traceback\|critical" | tail -3)
  if [ -n "$ERRORS" ]; then
    echo -e "  ${RED}[$C]${NC}"
    echo "$ERRORS" | while read -r line; do
      echo -e "    ${GRAY}$line${NC}"
    done
  fi
done

# ─── 7. ÖZET ────────────────────────────────────────────────
hdr "7. ÖZET"

RUNNING=$(docker ps --filter "name=prometheus_" --format "{{.Names}}" 2>/dev/null | wc -l | tr -d ' ')
TOTAL=18
echo -e "  Çalışan container: ${GREEN}${RUNNING}${NC} / ${TOTAL}"
echo -e "  Feature verisi: ${FEAT_COUNT:-0} sembol"
echo -e "  Aktif sinyal: ${SIG_COUNT:-0} sembol"
echo -e "  Ajan kararı: ${AGT_COUNT:-0} sembol"
echo ""

if [ "$FEAT_COUNT" -gt 0 ] && [ "$SIG_COUNT" -gt 0 ]; then
  echo -e "  ${GREEN}${BOLD}✓ SİSTEM GERÇEK VERİYLE ÇALIŞIYOR${NC}"
elif [ "$FEAT_COUNT" -gt 0 ]; then
  echo -e "  ${YELLOW}${BOLD}⚠ Özellikler var ama sinyal yok — signal_engine kontrol et${NC}"
else
  echo -e "  ${RED}${BOLD}✗ SİSTEM VERİ ÜRETMİYOR — data_ingestion ve feature_engine başlatılmalı${NC}"
fi
echo ""
