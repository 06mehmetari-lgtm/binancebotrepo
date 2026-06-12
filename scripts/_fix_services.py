#!/usr/bin/env python3
"""VPS servis teshis + otomatik restart."""
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
        ("PS", P + "docker compose ps -a --format 'table {{.Name}}\t{{.Status}}'"),
        ("SORUNLU", P + "docker compose ps -a --format '{{.Name}} {{.Status}}' | grep -iE 'exit|restart|unhealthy|created' || echo tumu running"),
        ("LOG feature", P + "docker compose logs feature_engine --tail 25 2>&1"),
        ("LOG agent", P + "docker compose logs agent_system --tail 25 2>&1"),
        ("LOG data", P + "docker compose logs data_ingestion --tail 15 2>&1"),
        ("LOG oms", P + "docker compose logs oms --tail 15 2>&1"),
        ("HEARTBEAT", P + 'RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-); for svc in data_ingestion feature_engine context_engine agent_system signal_engine learning_engine oms shadow_system immunity_system; do echo -n "$svc: "; docker compose exec -T redis redis-cli -a "$RP" --no-auth-warning GET "system:heartbeat:$svc" 2>/dev/null; echo; done'),
        ("RESTART", P + "docker compose restart feature_engine agent_system data_ingestion shadow_system immunity_system oms 2>&1"),
        ("WAIT", "sleep 15"),
        ("PS2", P + "docker compose ps --format 'table {{.Name}}\t{{.Status}}' | head -25"),
        ("HB2", P + 'RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-); NOW=$(date +%s); for svc in data_ingestion feature_engine agent_system shadow_system immunity_system oms; do TS=$(docker compose exec -T redis redis-cli -a "$RP" --no-auth-warning GET "system:heartbeat:$svc" 2>/dev/null|tr -d "\\r"); if [ -n "$TS" ] && [ "$TS" != "(nil)" ]; then AGE=$(python3 -c "print(int($NOW-float(\"$TS\")))" 2>/dev/null); echo "$svc OK ${AGE}s"; else echo "$svc BEKLENIYOR"; fi; done'),
    ]

    for title, cmd in cmds:
        print(f"\n{'='*50}\n{title}\n{'='*50}")
        _, o, e = c.exec_command(cmd if not cmd.startswith("sleep") else cmd, timeout=120)
        if cmd.startswith("sleep"):
            import time
            time.sleep(15)
            continue
        print(o.read().decode("utf-8", errors="replace"))
        err = e.read().decode("utf-8", errors="replace").strip()
        if err:
            print("ERR:", err[:300])
    c.close()


if __name__ == "__main__":
    main()
