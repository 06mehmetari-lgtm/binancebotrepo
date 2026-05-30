#!/bin/bash
# Prometheus Trading System — Sunucu Kurulum Scripti
# Kullanim: bash setup_server.sh
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[!!]${NC} $1"; }
err()  { echo -e "${RED}[ERR]${NC} $1"; exit 1; }

echo "╔══════════════════════════════════════════╗"
echo "║  PROMETHEUS TRADING SYSTEM — SETUP v1.0  ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 0. Root kontrolü ────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || err "Root olarak çalıştır: sudo bash setup_server.sh"

# ── 1. Sistem güncellemesi ───────────────────────────────────
log "Sistem güncelleniyor..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
log "Temel paketler kuruluyor..."
apt-get install -y -qq \
    curl wget git vim htop \
    ca-certificates gnupg lsb-release \
    python3.11 python3.11-pip python3.11-venv \
    ufw fail2ban \
    net-tools unzip

# ── 2. Docker kurulumu ──────────────────────────────────────
log "Docker kuruluyor..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | bash -s -- --quiet
else
    warn "Docker zaten kurulu, atlanıyor."
fi
systemctl enable docker --quiet
systemctl start docker
log "Docker Compose plugin kuruluyor..."
apt-get install -y -qq docker-compose-plugin
docker --version
docker compose version

# ── 3. Node.js 20 kurulumu ──────────────────────────────────
log "Node.js 20 kuruluyor..."
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - -quiet
    apt-get install -y -qq nodejs
else
    warn "Node.js zaten kurulu ($(node --version)), atlanıyor."
fi
node --version
npm --version

# ── 4. Güvenlik duvarı ──────────────────────────────────────
log "UFW firewall yapılandırılıyor..."
ufw --force reset > /dev/null
ufw default deny incoming > /dev/null
ufw default allow outgoing > /dev/null
ufw allow OpenSSH > /dev/null
ufw allow 3000/tcp comment 'Dashboard' > /dev/null
ufw allow 3001/tcp comment 'Grafana' > /dev/null
ufw allow 9090/tcp comment 'Prometheus metrics' > /dev/null
echo "y" | ufw enable > /dev/null
ufw status
log "Fail2ban başlatılıyor..."
systemctl enable fail2ban --quiet
systemctl start fail2ban

# ── 5. SSH güvenliği ────────────────────────────────────────
log "SSH güvenlik ayarları yapılıyor..."
sed -i 's/^#PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/^PermitRootLogin yes/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/^#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
# NOT: PasswordAuthentication kapatmak için önce SSH key ekleyin
# sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload sshd

# ── 6. Proje dizini oluştur ─────────────────────────────────
log "Proje dizini hazırlanıyor..."
mkdir -p /opt/prometheus
cd /opt/prometheus

# ── 7. Swap alanı (4GB) ─────────────────────────────────────
log "Swap alanı oluşturuluyor (4GB)..."
if [ ! -f /swapfile ]; then
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile -q
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    log "Swap aktif: $(free -h | grep Swap)"
else
    warn "Swap zaten mevcut, atlanıyor."
fi

# ── 8. Docker sistem optimizasyonları ─────────────────────────
log "Docker daemon yapılandırılıyor..."
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<EOF
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  },
  "default-ulimits": {
    "nofile": {
      "Name": "nofile",
      "Hard": 64000,
      "Soft": 64000
    }
  }
}
EOF
systemctl restart docker
log "Docker daemon yeniden başlatıldı."

# ── 9. OS optimizasyonları ────────────────────────────────────
log "Kernel parametreleri optimize ediliyor..."
cat >> /etc/sysctl.conf <<EOF

# Prometheus Trading Optimizasyonları
vm.swappiness=10
net.core.somaxconn=65535
net.ipv4.tcp_max_syn_backlog=65535
net.core.netdev_max_backlog=5000
fs.file-max=2097152
EOF
sysctl -p --quiet

# ── 10. Yardımcı scriptler ────────────────────────────────────
log "Yardımcı komutlar oluşturuluyor..."

cat > /usr/local/bin/prom-status <<'SCRIPT'
#!/bin/bash
cd /opt/prometheus
echo "=== Container Durumu ==="
docker compose ps
echo ""
echo "=== Sistem Kaynakları ==="
free -h
df -h /
echo ""
echo "=== CPU Yükü ==="
uptime
SCRIPT
chmod +x /usr/local/bin/prom-status

cat > /usr/local/bin/prom-logs <<'SCRIPT'
#!/bin/bash
cd /opt/prometheus
docker compose logs -f --tail=100 "${1:-}"
SCRIPT
chmod +x /usr/local/bin/prom-logs

cat > /usr/local/bin/prom-restart <<'SCRIPT'
#!/bin/bash
cd /opt/prometheus
docker compose restart "${1:-}"
SCRIPT
chmod +x /usr/local/bin/prom-restart

# ── 11. Özet ─────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║              KURULUM TAMAMLANDI                  ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  Sonraki adımlar:                                ║"
echo "║  1. cd /opt/prometheus                           ║"
echo "║  2. git clone <repo> . (veya dosyaları kopyala) ║"
echo "║  3. cp .env.example .env && nano .env            ║"
echo "║  4. docker compose up -d                         ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  Yardımcı komutlar:                              ║"
echo "║  prom-status   → servis durumu                   ║"
echo "║  prom-logs     → logları izle                    ║"
echo "║  prom-restart  → servis yeniden başlat           ║"
echo "╠══════════════════════════════════════════════════╣"
printf "║  Dashboard : http://%-28s ║\n" "$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_IP'):3000"
printf "║  Grafana   : http://%-28s ║\n" "$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_IP'):3001"
printf "║  Prometheus: http://%-28s ║\n" "$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_IP'):9090"
echo "╚══════════════════════════════════════════════════╝"
