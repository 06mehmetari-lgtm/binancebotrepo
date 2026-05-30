#!/bin/bash
# Prometheus Trading System — .env Oluşturucu
# Kullanım: bash setup_env.sh
# Sunucuda: curl -fsSL https://raw.githubusercontent.com/06mehmetari-lgtm/binancebotrepo/main/setup_env.sh | bash

set -e
TARGET="/opt/prometheus/.env"

# Eğer /opt/prometheus yoksa mevcut dizine yaz
if [ ! -d "/opt/prometheus" ]; then
    TARGET="$(pwd)/.env"
fi

if [ -f "$TARGET" ]; then
    echo "[!!] $TARGET zaten mevcut — üzerine yazmak istiyor musun? (e/h)"
    read -r CONFIRM
    [ "$CONFIRM" != "e" ] && echo "İptal edildi." && exit 0
fi

cat > "$TARGET" << 'ENVEOF'
# ═══════════════════════════════════════════════════════════
# PROMETHEUS TRADING SYSTEM — .env
# DRY_RUN=true ile başla, shadow sistem onayladıktan sonra false yap
# ═══════════════════════════════════════════════════════════

# ───────────────────────────────
# Binance USDM Futures
# ───────────────────────────────
BINANCE_API_KEY=BURAYA_BINANCE_API_KEY
BINANCE_SECRET=BURAYA_BINANCE_SECRET
TRADING_SYMBOLS=BTCUSDT,ETHUSDT,BNBUSDT
DRY_RUN=true

# ───────────────────────────────
# PostgreSQL
# ───────────────────────────────
POSTGRES_USER=prometheus
POSTGRES_PASSWORD=BURAYA_POSTGRES_SIFRE

# ───────────────────────────────
# TimescaleDB
# ───────────────────────────────
TIMESCALE_USER=tsuser
TIMESCALE_PASSWORD=BURAYA_TIMESCALE_SIFRE

# ───────────────────────────────
# Redis
# ───────────────────────────────
REDIS_PASSWORD=BURAYA_REDIS_SIFRE

# ───────────────────────────────
# Monitoring
# ───────────────────────────────
GRAFANA_PASSWORD=BURAYA_GRAFANA_SIFRE

# ───────────────────────────────
# Reddit API (ücretsiz)
# reddit.com/prefs/apps → "script" türü uygulama oluştur
# ───────────────────────────────
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=PrometheusTrader/1.0

# ───────────────────────────────
# CryptoPanic (ücretsiz)
# cryptopanic.com/developers/api
# ───────────────────────────────
CRYPTOPANIC_KEY=

# ───────────────────────────────
# FRED Macro API (ücretsiz)
# fred.stlouisfed.org/docs/api/api_key.html
# ───────────────────────────────
FRED_API_KEY=

# ───────────────────────────────
# Etherscan On-Chain (ücretsiz)
# etherscan.io/apis
# ───────────────────────────────
ETHERSCAN_KEY=

# ───────────────────────────────
# Anthropic (opsiyonel — debate agent için)
# console.anthropic.com/settings/keys
# ───────────────────────────────
ANTHROPIC_API_KEY=
ENVEOF

echo ""
echo "✓ .env oluşturuldu: $TARGET"
echo ""
echo "ZORUNLU: Aşağıdaki değerleri doldur:"
echo "  nano $TARGET"
echo ""
echo "  BINANCE_API_KEY   → Binance → API Management → Futures izni ver"
echo "  BINANCE_SECRET    → yukarıdaki ile aynı yerden"
echo "  POSTGRES_PASSWORD → istediğin güçlü şifre (min 16 karakter)"
echo "  TIMESCALE_PASSWORD→ istediğin güçlü şifre"
echo "  REDIS_PASSWORD    → istediğin güçlü şifre"
echo "  GRAFANA_PASSWORD  → istediğin şifre"
echo ""
echo "Doldurunca: docker compose up -d"
