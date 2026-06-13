#!/usr/bin/env python3
"""Fix DOWN services: risk_limits IndentationError + restart + verify."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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

    prom_dir = s.get("VPS_PROJECT_DIR", "/root/prometheus")
    local_rl = ROOT / "services/shared/risk_limits.py"
    if not local_rl.exists():
        print("HATA: services/shared/risk_limits.py yok")
        return 1

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        s["VPS_HOST"], username=s.get("VPS_USER", "root"), password=s["VPS_PASS"],
        timeout=30, allow_agent=False, look_for_keys=False,
    )

    def run(cmd: str, timeout: int = 90) -> str:
        _, o, e = c.exec_command(cmd, timeout=timeout)
        out = o.read().decode("utf-8", errors="replace")
        err = e.read().decode("utf-8", errors="replace")
        return (out + err).strip()

    print("=" * 60)
    print("  FIX DOWN SERVICES")
    print("=" * 60)

    sftp = c.open_sftp()
    remote_repo = f"{prom_dir}/services/shared/risk_limits.py"
    remote_tmp = "/tmp/risk_limits_fix.py"
    sftp.put(str(local_rl), remote_tmp)
    sftp.put(str(local_rl), remote_repo)
    sftp.close()
    print(f"  OK  risk_limits.py -> {remote_repo}")

    # Repo dosyasini dogrula
    repo_check = run(f"sed -n '148,152p' {remote_repo}")
    print(f"  repo satir 148-152:\n{repo_check}")

    targets = [
        ("prometheus_signal", "/app/risk_limits.py"),
        ("prometheus_immunity", "/app/risk_limits.py"),
        ("prometheus_oms", "/app/risk_limits.py"),
        ("prometheus_shadow", "/app/risk_limits.py"),
    ]

    print("\n=== stop (cp icin) ===")
    print(run(f"cd {prom_dir} && docker compose stop signal_engine immunity_system 2>&1"))

    for container, dest in targets:
        out = run(f"docker cp {remote_tmp} {container}:{dest} 2>&1")
        if "Error" in out:
            print(f"  HATA {container}: {out[:200]}")
        else:
            print(f"  OK  docker cp -> {container}")

    print("\n=== restart signal_engine immunity_system learning_engine ===")
    print(run(f"cd {prom_dir} && docker compose start signal_engine immunity_system learning_engine 2>&1"))

    print("\n=== syntax check ===")
    for container in ("prometheus_signal", "prometheus_immunity"):
        out = run(f"docker exec {container} python -m py_compile /app/risk_limits.py 2>&1")
        print(f"  {container}: {'OK' if not out else out[:200]}")

    print("\n=== bekleniyor 30sn ===")
    time.sleep(30)

    print("\n=== container status ===")
    print(run(
        f"cd {prom_dir} && docker compose ps -a --format '{{{{.Name}}}}|{{{{.Status}}}}' "
        "| grep -E 'signal|immunity|learning'"
    ))

    print("\n=== son loglar ===")
    for svc in ("signal_engine", "immunity_system", "learning_engine"):
        print(f"\n--- {svc} ---")
        print(run(f"cd {prom_dir} && docker compose logs {svc} --tail 12 2>&1")[:1200])

    print("\n=== heartbeat ===")
    hb_cmd = (
        f"cd {prom_dir}; RP=$(grep '^REDIS_PASSWORD=' .env|cut -d= -f2-); "
        "NOW=$(date +%s); "
        "for svc in signal_engine immunity_system learning_engine; do "
        'TS=$(docker compose exec -T redis redis-cli -a "$RP" --no-auth-warning '
        'GET "system:heartbeat:$svc" 2>/dev/null|tr -d "\\r"); '
        'if [ -n "$TS" ] && [ "$TS" != "(nil)" ]; then '
        'AGE=$(python3 -c "print(int($NOW-float(\"$TS\")))" 2>/dev/null); '
        'echo "$svc OK ${AGE}s"; else echo "$svc DOWN"; fi; done'
    )
    print(run(hb_cmd))

    sig_count = run(
        f"cd {prom_dir}; RP=$(grep '^REDIS_PASSWORD=' .env|cut -d= -f2-); "
        'docker compose exec -T redis redis-cli -a "$RP" --no-auth-warning '
        '--scan --pattern "signal:latest:*" 2>/dev/null | wc -l'
    )
    print(f"\n  signal:latest keys: {sig_count.strip()}")

    c.close()
    print("\nBitti — dashboard /system sayfasini yenileyin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
