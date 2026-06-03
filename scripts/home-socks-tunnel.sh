#!/usr/bin/env bash
# Ev Linux/Mac — VPS'e ücretsiz SOCKS tüneli
# Kullanım: VPS_HOST=194.163.181.39 bash scripts/home-socks-tunnel.sh
set -euo pipefail
VPS_HOST="${VPS_HOST:-194.163.181.39}"
VPS_USER="${VPS_USER:-root}"
PORT="${SOCKS_PORT:-1080}"
echo "Ev PC -> ${VPS_USER}@${VPS_HOST} SOCKS :${PORT} (Ctrl+C = kopar)"
echo "VPS .env: ALL_PROXY=socks5://127.0.0.1:${PORT}"
exec ssh -N -R "${PORT}:127.0.0.1:${PORT}" "${VPS_USER}@${VPS_HOST}"
