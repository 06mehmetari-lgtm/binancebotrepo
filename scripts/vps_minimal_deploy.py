#!/usr/bin/env python3
"""Minimal deploy — sadece 4 pipeline servisi build+restart (~5-12 dk, dashboard YOK)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"
MINIMAL = ("shadow_system", "agent_system", "signal_engine", "oms")


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
    prom_dir = s.get("VPS_PROJECT_DIR", "/root/prometheus")
    P = f"cd {prom_dir}; "
    svcs = " ".join(MINIMAL)

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=s.get("VPS_USER", "root"), password=s["VPS_PASS"],
                timeout=30, allow_agent=False, look_for_keys=False)

    print("=" * 60)
    print("  MINIMAL DEPLOY — 4 servis build (dashboard YOK)")
    print(f"  {', '.join(MINIMAL)}")
    print("=" * 60)

    steps = [
        ("git pull", P + "git pull origin master 2>&1 | tail -5", 120),
        ("build", P + f"docker compose build --parallel {svcs} 2>&1 | tail -25", 900),
        ("up", P + f"docker compose up -d {svcs} 2>&1", 120),
    ]
    for title, cmd, timeout in steps:
        print(f"\n=== {title} ===")
        _, o, e = c.exec_command(cmd, timeout=timeout)
        out = o.read().decode("utf-8", errors="replace")
        err = e.read().decode("utf-8", errors="replace").strip()
        print(out or err or "(bos)")

    print("\n=== heartbeat (30 sn) ===")
    time.sleep(30)
    hb_cmd = P + r"""RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-); NOW=$(date +%s)
for svc in shadow_system agent_system signal_engine oms; do
  TS=$(docker compose exec -T redis redis-cli -a "$RP" --no-auth-warning GET "system:heartbeat:$svc" 2>/dev/null|tr -d '\r')
  if [ -n "$TS" ] && [ "$TS" != "(nil)" ]; then
    AGE=$(python3 -c "print(int($NOW-float('$TS')))" 2>/dev/null)
    echo "$svc OK ${AGE}s"
  else
    echo "$svc BEKLENIYOR"
  fi
done"""
    _, o, _ = c.exec_command(hb_cmd, timeout=60)
    print(o.read().decode("utf-8", errors="replace"))

    print(f"\nBitti — http://{host}:3000/system")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
