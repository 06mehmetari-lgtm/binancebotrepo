#!/usr/bin/env python3
"""Hard-fix risk_limits on VPS — stop, cp, verify, start."""
from pathlib import Path
import paramiko

ROOT = Path(__file__).resolve().parent.parent
SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"
PROM = "/root/prometheus"


def main() -> int:
    s: dict[str, str] = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            s[k.strip()] = v.strip()

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        s["VPS_HOST"], username=s.get("VPS_USER", "root"), password=s["VPS_PASS"],
        timeout=30, allow_agent=False, look_for_keys=False,
    )

    def run(cmd: str, timeout: int = 180) -> str:
        _, o, e = c.exec_command(cmd, timeout=timeout)
        return (o.read() + e.read()).decode("utf-8", errors="replace")

    local = ROOT / "services/shared/risk_limits.py"
    sftp = c.open_sftp()
    sftp.put(str(local), f"{PROM}/services/shared/risk_limits.py")
    sftp.close()

    bash = """#!/bin/bash
set -e
cd """ + PROM + """
SRC=""" + PROM + """/services/shared/risk_limits.py
docker compose stop signal_engine immunity_system
for ctr in prometheus_signal prometheus_immunity; do
  docker cp "$SRC" $ctr:/app/risk_limits.py
done
docker compose start signal_engine immunity_system
sleep 25
echo '=== FILE signal ==='
docker exec prometheus_signal sed -n '148,152p' /app/risk_limits.py || true
echo '=== FILE immunity ==='
docker exec prometheus_immunity sed -n '148,152p' /app/risk_limits.py || true
echo '=== COMPILE ==='
docker exec prometheus_signal python -m py_compile /app/risk_limits.py && echo signal_OK
docker exec prometheus_immunity python -m py_compile /app/risk_limits.py && echo immunity_OK
echo '=== PS ==='
docker compose ps signal_engine immunity_system learning_engine
echo '=== HB ==='
RP=$(grep '^REDIS_PASSWORD=' .env|cut -d= -f2-)
NOW=$(date +%s)
for svc in signal_engine immunity_system learning_engine; do
  TS=$(docker compose exec -T redis redis-cli -a "$RP" --no-auth-warning GET "system:heartbeat:$svc" 2>/dev/null|tr -d '\r')
  if [ -n "$TS" ] && [ "$TS" != "(nil)" ]; then
    AGE=$(python3 -c "import time; print(int(time.time()-float('$TS')))")
    echo "$svc OK ${AGE}s"
  else echo "$svc DOWN"; fi
done
echo signal_keys=$(docker compose exec -T redis redis-cli -a "$RP" --no-auth-warning --scan --pattern 'signal:latest:*' 2>/dev/null | wc -l)
echo '=== LOG ==='
docker compose logs signal_engine --tail 8 2>&1
"""
    sftp = c.open_sftp()
    sftp.file("/tmp/hard_fix.sh", "w").write(bash)
    sftp.close()
    print(run("chmod +x /tmp/hard_fix.sh && bash /tmp/hard_fix.sh"))
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
