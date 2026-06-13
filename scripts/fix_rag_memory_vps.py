#!/usr/bin/env python3
"""rag_memory VPS duzeltmesi — REDIS_URL eksikligi + recreate."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"

REMOTE_SCRIPT = r"""
set -e
cd /root/prometheus

# docker-compose.yml: rag_memory REDIS_URL yoksa ekle
python3 <<'PY'
from pathlib import Path
p = Path("docker-compose.yml")
t = p.read_text(encoding="utf-8")
if "rag_memory:" not in t:
    raise SystemExit("rag_memory servisi bulunamadi")
block = t.split("rag_memory:", 1)[1].split("\n  scenario_engine:", 1)[0]
changed = False
if "REDIS_URL" not in block:
    old = "    environment:\n      - QDRANT_URL=http://qdrant:6333"
    new = (
        "    environment:\n"
        "      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379\n"
        "      - QDRANT_URL=http://qdrant:6333"
    )
    if old in t:
        t = t.replace(old, new, 1)
        changed = True
if "depends_on:\n      - qdrant\n      - postgres" in block and "- redis" not in block:
    t = t.replace(
        "  rag_memory:" + block,
        "  rag_memory:" + block.replace(
            "depends_on:\n      - qdrant",
            "depends_on:\n      - redis\n      - qdrant",
            1,
        ),
        1,
    )
    changed = True
if changed:
    p.write_text(t, encoding="utf-8")
    print("compose: REDIS_URL eklendi")
else:
    print("compose: zaten guncel")
PY

git pull origin master 2>/dev/null || true
docker compose up -d --force-recreate rag_memory
sleep 8
docker ps --filter name=prometheus_rag --format '{{.Status}}'
docker logs prometheus_rag --tail 15 2>&1
"""


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
    script = REMOTE_SCRIPT.replace("/root/prometheus", prom_dir)

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Baglaniyor: {host}...")
    c.connect(
        host,
        username=s.get("VPS_USER", "root"),
        password=s["VPS_PASS"],
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    _, stdout, stderr = c.exec_command(script, timeout=600)
    out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace")
    print(out)
    c.close()

    if "Up" in out and "Authentication required" not in out:
        print("\nOK — rag_memory ayakta olmali")
        return 0
    if "rag_memory starting" in out.lower():
        print("\nOK — rag_memory basladi")
        return 0
    print("\nUYARI — loglari kontrol edin; gerekirse DEPLOY.bat calistirin")
    return 1


if __name__ == "__main__":
    sys.exit(main())
