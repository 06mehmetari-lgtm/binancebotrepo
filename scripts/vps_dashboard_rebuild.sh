#!/bin/bash
# VPS'te takilan dashboard build'i bitirmek / yeniden baslatmak icin.
set -eu
cd /root/prometheus 2>/dev/null || cd ~/prometheus

echo "=== Dashboard rebuild (cache + swap) ==="
pkill -f 'docker compose build.*dashboard' 2>/dev/null || true
sleep 2

if ! swapon --show 2>/dev/null | grep -q swapfile; then
  if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 2>/dev/null
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile 2>/dev/null || true
fi
free -h | head -3

docker compose stop neat_evolution rl_agent backtest scenario_engine 2>/dev/null || true
SHA=$(git rev-parse HEAD | cut -c1-12)
echo "BUILD dashboard CACHEBUST=$SHA"
docker compose build --build-arg CACHEBUST="$SHA" dashboard
docker compose up -d dashboard
docker compose start neat_evolution rl_agent backtest scenario_engine 2>/dev/null || true

sleep 15
curl -sS -m 20 -o /dev/null -w 'capital API: %{http_code}\n' http://127.0.0.1:3000/api/portfolio/capital
curl -sS -m 20 http://127.0.0.1:3000/api/deploy-version | head -c 200
echo ""
echo "=== Bitti — http://$(hostname -I | awk '{print $1}'):3000/positions#kasa ==="
