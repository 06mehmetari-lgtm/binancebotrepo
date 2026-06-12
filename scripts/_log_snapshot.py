#!/usr/bin/env python3
"""VPS log snapshot — al/sat/tarama özeti."""
from __future__ import annotations

import json
import re
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "scripts" / ".deploy.secrets"


def load_secrets() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def run_cmd(client: paramiko.SSHClient, cmd: str, timeout: int = 90) -> str:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if err and not out:
        return f"(stderr) {err[:300]}"
    return out or "(bos)"


def main() -> None:
    s = load_secrets()
    host = s.get("VPS_HOST", "194.163.181.39")
    user = s.get("VPS_USER", "root")
    pwd = s["VPS_PASS"]
    P = "cd /root/prometheus 2>/dev/null; "

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=pwd, timeout=30, allow_agent=False, look_for_keys=False)

    sections: list[tuple[str, str]] = [
        ("KONTEYNERLER", 'docker ps --format "{{.Names}}|{{.Status}}" | grep prometheus || true'),
        ("GIT", P + "git log -1 --oneline"),
        ("TARANAN COINLER", P + "grep -E '^TRADING_SYMBOLS=' .env || echo TRADING_SYMBOLS=?"),
        (
            "OMS — AL/SAT/KAPAT",
            P + r'docker compose logs oms --tail 120 2>/dev/null | grep -iE "buy|sell|open|close|order|position|filled|entry|reject" | tail -45',
        ),
        (
            "SIGNAL ENGINE — SİNYALLER",
            P + r'docker compose logs signal_engine --tail 100 2>/dev/null | grep -iE "signal|flat|long|short|confidence|scan|symbol|suppress" | tail -40',
        ),
        (
            "AGENT/GUARD — POZİSYON KARARI",
            P + r'docker compose logs agent_system --tail 100 2>/dev/null | grep -iE "guard|close|hold|chart|consensus|position|debate|verdict" | tail -40',
        ),
        (
            "FEATURE ENGINE — TARAMA",
            P + r'docker compose logs feature_engine --tail 60 2>/dev/null | grep -iE "symbol|feature|computed|BTC|ETH|BNB|SOL" | tail -25',
        ),
        (
            "DATA INGESTION — STREAM",
            P + r'docker compose logs data_ingestion --tail 40 2>/dev/null | grep -iE "symbol|stream|subscribe|kline|ticker|ws" | tail -20',
        ),
        (
            "SHADOW — KAĞIT İŞLEM",
            P + r'docker compose logs shadow_system --tail 50 2>/dev/null | grep -iE "paper|fill|promot|trade|symbol" | tail -25',
        ),
    ]

    for title, cmd in sections:
        print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
        print(run_cmd(c, cmd))

    rp_cmd = (
        P + 'RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-); '
        'echo "=== ACIK POZISYONLAR ==="; '
        'for k in $(docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning KEYS "oms:position:*" 2>/dev/null); do '
        'echo "--- $k ---"; docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning GET "$k" 2>/dev/null | head -c 500; echo; done; '
        'echo "=== SON SINYALLER ==="; '
        'for sym in BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT DOGEUSDT ADAUSDT AVAXUSDT LINKUSDT MATICUSDT; do '
        'raw=$(docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning GET signal:latest:$sym 2>/dev/null); '
        'if [ -n "$raw" ] && [ "$raw" != "(nil)" ]; then '
        'echo "$sym: $(echo $raw | python3 -c \'import sys,json; d=json.load(sys.stdin); print(d.get(\"direction\",\"?\"), \"conf\", round(float(d.get(\"confidence\",0)),2), \"action\", (d.get(\"decision\") or {}).get(\"action\",\"?\"))\' 2>/dev/null || echo ok)"; fi; done; '
        'echo "=== SYSTEM STATUS ==="; '
        'docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning GET system:status 2>/dev/null | head -c 800'
    )
    print(f"\n{'=' * 60}\nREDIS CANLI DURUM\n{'=' * 60}")
    print(run_cmd(c, rp_cmd, timeout=120))

    c.close()


if __name__ == "__main__":
    main()
