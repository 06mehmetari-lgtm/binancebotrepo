#!/usr/bin/env python3
"""SSH sifre + baglanti testi."""
from __future__ import annotations

import sys
import time
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
        print("  1) SSH_SIFRE_DEGISTIR.bat calistirin")
        print("  2) veya copy scripts\\.deploy.secrets.example scripts\\.deploy.secrets")
        return 1

    s: dict[str, str] = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            s[k.strip()] = v.strip()

    host = s.get("VPS_HOST", "194.163.181.39")
    user = s.get("VPS_USER", "root")
    pwd = s.get("VPS_PASS", "")
    if not pwd:
        print("HATA: VPS_PASS bos — SSH_SIFRE_DEGISTIR.bat calistirin")
        return 1

    print()
    print("=" * 50)
    print("  SSH BAGLANTI TESTI")
    print("=" * 50)
    print(f"  Host: {user}@{host}")
    print(f"  Sifre: {'*' * min(len(pwd), 12)} ({len(pwd)} karakter)")
    print()

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        t0 = time.time()
        c.connect(host, username=user, password=pwd, timeout=20, allow_agent=False, look_for_keys=False)
        ms = int((time.time() - t0) * 1000)
        print(f"  [OK] SSH baglandi ({ms} ms)")
    except paramiko.AuthenticationException:
        print("  [HATA] Kimlik dogrulama BASARISIZ — sifre yanlis")
        print("  Cozum: Sunucu panelinden sifreyi kontrol edin, sonra SSH_SIFRE_DEGISTIR.bat")
        return 1
    except Exception as exc:
        print(f"  [HATA] Baglanti: {exc}")
        return 1

    checks = [
        ("hostname", "hostname && uptime | head -1"),
        ("prometheus", "test -d /root/prometheus && echo DIR_OK || echo DIR_MISSING"),
        ("redis", "cd /root/prometheus && docker compose exec -T redis redis-cli -a $(grep '^REDIS_PASSWORD=' .env|cut -d= -f2-) --no-auth-warning PING 2>/dev/null"),
        ("trade_count", "cd /root/prometheus && RP=$(grep '^REDIS_PASSWORD=' .env|cut -d= -f2-); docker compose exec -T redis redis-cli -a \"$RP\" --no-auth-warning LLEN oms:trade_history 2>/dev/null"),
    ]

    for name, cmd in checks:
        try:
            _, o, e = c.exec_command(cmd, timeout=30)
            out = o.read().decode("utf-8", errors="replace").strip()
            err = e.read().decode("utf-8", errors="replace").strip()
            val = out or err or "(bos)"
            ok = "HATA" not in val.upper() and "MISSING" not in val and "NOAUTH" not in val.upper()
            if name == "redis":
                ok = "PONG" in val
            if name == "prometheus":
                ok = "DIR_OK" in val
            mark = "OK" if ok else "!"
            print(f"  [{mark}] {name}: {val[:80]}")
        except Exception as exc:
            print(f"  [!] {name}: {exc}")

    c.close()
    print()
    print("  SSH calisiyorsa: KARLILIK_TESHIS.bat acilabilir")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
