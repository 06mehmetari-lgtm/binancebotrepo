#!/usr/bin/env python3
"""VPS deploy + dashboard yansima kontrolu (sifre dosyadan)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"


def run_local(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    return ((r.stdout or "") + (r.stderr or "")).strip()


def main() -> int:
    if not SECRETS.exists():
        print("HATA: scripts/.deploy.secrets yok")
        return 1
    s: dict[str, str] = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            s[k.strip()] = v.strip()

    try:
        import paramiko
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
        import paramiko

    prom = s.get("VPS_PROJECT_DIR", "/root/prometheus")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        s["VPS_HOST"], username=s.get("VPS_USER", "root"), password=s["VPS_PASS"],
        timeout=30, allow_agent=False, look_for_keys=False,
    )

    pc_sha = run_local(["git", "rev-parse", "--short", "HEAD"]).splitlines()[-1]

    checks = [
        ("PC HEAD", f"echo LOCAL_ONLY:{pc_sha}"),
        ("VPS git", f"cd {prom} && git rev-parse --short HEAD && git log -1 --oneline"),
        ("Deploy panel kaynak", f"cd {prom} && test -f services/dashboard/src/app/components/DeployStatusPanel.tsx && echo SRC_OK || echo SRC_MISSING"),
        ("Deploy panel container", "docker exec prometheus_dashboard sh -c 'test -f /app/src/app/components/DeployStatusPanel.tsx && echo CTR_OK || echo CTR_OLD' 2>/dev/null || echo CTR_DOWN"),
        ("Dashboard durum", f"cd {prom} && docker compose ps dashboard"),
        (".deploy_last_sha", f"cat {prom}/.deploy_last_sha 2>/dev/null || echo YOK"),
        ("Son deploy redis", f"cd {prom} && RP=$(grep REDIS_PASSWORD .env | cut -d= -f2 | tr -d '\"') && docker exec prometheus_redis redis-cli -a \"$RP\" --no-auth-warning GET system:deploy:version 2>/dev/null"),
        ("API deploy-version", "curl -sS -m 15 -w '\\nHTTP:%{http_code}' http://127.0.0.1:3000/api/deploy-version 2>&1 | tail -5"),
        ("Ana sayfa boyut", "curl -sS -m 15 -w 'HTTP:%{http_code} SIZE:%{size_download}' -o /tmp/prom_home.html http://127.0.0.1:3000/ 2>&1; grep -oE 'Son DEPLOY|DeployStatus|20260613|Prometheus' /tmp/prom_home.html | head -8; wc -c /tmp/prom_home.html"),
        ("Dashboard log", "docker logs prometheus_dashboard 2>&1 | tail -8"),
        ("Image olusturma", "docker inspect prometheus_dashboard --format '{{.Image}} {{.Created}}' 2>/dev/null"),
    ]

    print("=" * 60)
    print("  VPS DEPLOY KONTROL")
    print("=" * 60)
    for title, cmd in checks:
        if cmd.startswith("echo LOCAL_ONLY:"):
            print(f"\n[{title}]")
            print(f"  {cmd.split(':', 1)[1]}")
            continue
        _, o, e = c.exec_command(cmd, timeout=90)
        out = (o.read() + e.read()).decode("utf-8", errors="replace").strip()
        print(f"\n[{title}]")
        for line in out.splitlines()[:15]:
            print(f"  {line}")

    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
