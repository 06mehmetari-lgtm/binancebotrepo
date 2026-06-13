#!/usr/bin/env python3
"""Arka plan build durumu — VPS /tmp/prometheus_bg_build.log"""
from __future__ import annotations

import sys
from pathlib import Path

SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"


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

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(s["VPS_HOST"], username=s.get("VPS_USER", "root"), password=s["VPS_PASS"],
              timeout=30, allow_agent=False, look_for_keys=False)

    cmds = [
        ("PID", "cat /tmp/prometheus_bg_build.pid 2>/dev/null || echo yok"),
        ("Durum", "grep -E 'BG_START|BG_DONE|BG_FAILED|BUILD_EXIT' /tmp/prometheus_bg_build.log 2>/dev/null | tail -5 || echo henuz baslamadi"),
        ("Son satirlar", "tail -8 /tmp/prometheus_bg_build.log 2>/dev/null || echo log yok"),
        ("Container", "cd /root/prometheus && docker compose ps --format '{{.Name}} {{.Status}}' 2>/dev/null | head -20"),
    ]

    print("=" * 60)
    print("  ARKA PLAN BUILD DURUMU")
    print("=" * 60)
    for title, cmd in cmds:
        print(f"\n--- {title} ---")
        _, o, e = c.exec_command(cmd, timeout=60)
        print(o.read().decode("utf-8", errors="replace") or e.read().decode("utf-8", errors="replace"))

    print("\n" + "=" * 60)
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
