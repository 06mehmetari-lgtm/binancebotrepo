#!/usr/bin/env python3
from pathlib import Path
import paramiko

SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"


def main():
    s = {}
    for line in (Path(__file__).resolve().parent / ".deploy.secrets").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            s[k.strip()] = v.strip()

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(s["VPS_HOST"], username=s["VPS_USER"], password=s["VPS_PASS"], timeout=30, allow_agent=False, look_for_keys=False)
    P = "cd /root/prometheus; "

    cmds = [
        ("TRXUSDT LOG", P + r"docker compose logs oms --since 48h 2>/dev/null | grep -i TRXUSDT | tail -25"),
        ("OMS OPEN LOG", P + r"docker compose logs oms --since 48h 2>/dev/null | grep -iE 'opened|opening|new position|entry|TRX|SOPH|ESPORT' | grep -iv risk_limits | tail -30"),
        ("SIGNAL TRX", P + r"docker compose logs signal_engine --since 2h 2>/dev/null | grep TRXUSDT | tail -10"),
        ("GUARD TRX SOPH", P + r"docker compose logs agent_system --since 2h 2>/dev/null | grep -iE 'TRXUSDT|SOPHUSDT|ESPORTS' | tail -20"),
        ("PG TABLES", P + r"docker exec prometheus_postgres psql -U prometheus -d prometheus_trading -t -c \"SELECT count(*) FROM trades;\" 2>&1"),
        ("SHADOW STATE", P + 'RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-); docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning GET shadow:leaderboard 2>/dev/null | head -c 1000'),
        ("ALL GUARD KEYS", P + 'RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-); docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning KEYS "guard:position:*"'),
        ("OMS ALL POS KEYS", P + 'RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-); docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning KEYS "oms:position:*"'),
    ]
    for t, cmd in cmds:
        print(f"\n=== {t} ===")
        _, o, _ = c.exec_command(cmd, timeout=90)
        print(o.read().decode("utf-8", errors="replace").strip() or "(bos)")
    c.close()


if __name__ == "__main__":
    main()
