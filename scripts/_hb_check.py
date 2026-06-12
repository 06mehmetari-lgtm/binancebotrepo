#!/usr/bin/env python3
"""VPS heartbeat kontrolu (restart yok)."""
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
        ("HEARTBEATS", P + r"""RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-); NOW=$(date +%s); for svc in data_ingestion feature_engine context_engine agent_system signal_engine learning_engine shadow_system immunity_system oms; do TS=$(docker compose exec -T redis redis-cli -a "$RP" --no-auth-warning GET "system:heartbeat:$svc" 2>/dev/null|tr -d '\r'); if [ -n "$TS" ] && [ "$TS" != "(nil)" ]; then AGE=$(python3 -c "print(int($NOW-float('$TS')))" 2>/dev/null); echo "$svc OK ${AGE}s"; else echo "$svc MISSING"; fi; done"""),
        ("LOG data", P + "docker compose logs data_ingestion --tail 12 2>&1"),
        ("LOG shadow", P + "docker compose logs shadow_system --tail 8 2>&1"),
        ("LOG immunity", P + "docker compose logs immunity_system --tail 8 2>&1"),
        ("LOG oms", P + "docker compose logs oms --tail 8 2>&1"),
    ]

    for title, cmd in cmds:
        print(f"\n=== {title} ===")
        _, o, e = c.exec_command(cmd, timeout=90)
        print(o.read().decode("utf-8", errors="replace"))
        err = e.read().decode("utf-8", errors="replace").strip()
        if err:
            print("ERR:", err[:200])
    c.close()


if __name__ == "__main__":
    main()
