#!/usr/bin/env python3
"""Eski heartbeat imajlarini VPS'te rebuild + restart (4 servis, ~5-8 dk)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"
STALE = ("data_ingestion", "shadow_system", "immunity_system", "oms")


def main() -> int:
    try:
        import paramiko
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
        import paramiko

    if not SECRETS.exists():
        print("HATA: scripts/.deploy.secrets yok")
        return 1

    s: dict[str, str] = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            s[k.strip()] = v.strip()

    host = s.get("VPS_HOST", "194.163.181.39")
    user = s.get("VPS_USER", "root")
    prom_dir = s.get("VPS_PROJECT_DIR", "/root/prometheus")
    P = f"cd {prom_dir}; "

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=s["VPS_PASS"], timeout=30, allow_agent=False, look_for_keys=False)

    steps = [
        ("git pull", P + "git pull origin master 2>&1 | tail -3"),
        ("build", P + f"docker compose build {' '.join(STALE)} 2>&1 | tail -20"),
        ("up", P + f"docker compose up -d {' '.join(STALE)} 2>&1"),
        ("wait", "sleep 25"),
        ("hb", P + r"""RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-); NOW=$(date +%s)
for svc in data_ingestion shadow_system immunity_system oms; do
  TS=$(docker compose exec -T redis redis-cli -a "$RP" --no-auth-warning GET "system:heartbeat:$svc" 2>/dev/null|tr -d '\r')
  if [ -n "$TS" ] && [ "$TS" != "(nil)" ]; then
    AGE=$(python3 -c "print(int($NOW-float('$TS')))" 2>/dev/null)
    echo "$svc OK ${AGE}s"
  else
    echo "$svc BEKLENIYOR"
  fi
done"""),
    ]

    for title, cmd in steps:
        print(f"\n=== {title} ===")
        if cmd.startswith("sleep"):
            time.sleep(25)
            continue
        _, o, e = c.exec_command(cmd, timeout=600 if title == "build" else 120)
        out = o.read().decode("utf-8", errors="replace")
        err = e.read().decode("utf-8", errors="replace").strip()
        print(out or err or "(bos)")

    print(f"\nBitti — http://{host}:3000/system")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
