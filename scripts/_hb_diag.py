#!/usr/bin/env python3
"""VPS container icinde heartbeat kodu var mi?"""
from pathlib import Path
import paramiko

SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"


def main():
    s = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            s[k.strip()] = v.strip()

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(s["VPS_HOST"], username=s["VPS_USER"], password=s["VPS_PASS"], timeout=30, allow_agent=False, look_for_keys=False)
    P = "cd /root/prometheus; "

    cmds = [
        ("grep heartbeat", P + r"""for svc in data_ingestion shadow_system immunity_system oms agent_system; do echo "== $svc =="; docker compose exec -T $svc grep -l "system:heartbeat" /app/main.py 2>/dev/null || echo YOK; done"""),
        ("agent log", P + "docker compose logs agent_system --tail 20 2>&1"),
        ("shadow start", P + "docker compose logs shadow_system 2>&1 | grep -E 'starting|tracking|heartbeat|ERROR' | tail -15"),
        ("immunity err", P + "docker compose logs immunity_system 2>&1 | grep -iE 'error|heartbeat|starting' | tail -15"),
        ("oms start", P + "docker compose logs oms 2>&1 | grep -E 'starting|heartbeat|ERROR|portfolio' | tail -15"),
        ("data start", P + "docker compose logs data_ingestion 2>&1 | grep -E 'starting|heartbeat|Order books' | tail -10"),
    ]

    for title, cmd in cmds:
        print(f"\n=== {title} ===")
        _, o, e = c.exec_command(cmd, timeout=90)
        print(o.read().decode("utf-8", errors="replace"))
    c.close()


if __name__ == "__main__":
    main()
