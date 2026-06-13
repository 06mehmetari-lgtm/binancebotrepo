#!/usr/bin/env python3
"""
Build YOK — degisen Python dosyalarini container'a kopyala + restart (~1-3 dk).

Kullanim: HOT_PATCH.bat  veya  python scripts/vps_hot_patch.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"

# (repo dosyasi, [(container, hedef yol), ...])
PATCH_MAP: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "services/shared/risk_limits.py",
        [
            ("prometheus_signal", "/app/risk_limits.py"),
            ("prometheus_immunity", "/app/risk_limits.py"),
            ("prometheus_oms", "/app/risk_limits.py"),
            ("prometheus_shadow", "/app/risk_limits.py"),
        ],
    ),
    (
        "services/shared/profit_rules.py",
        [
            ("prometheus_shadow", "/app/profit_rules.py"),
            ("prometheus_oms", "/app/profit_rules.py"),
            ("prometheus_agents", "/app/profit_rules.py"),
            ("prometheus_signal", "/app/profit_rules.py"),
            ("prometheus_immunity", "/app/profit_rules.py"),
        ],
    ),
    ("services/shadow_system/main.py", [("prometheus_shadow", "/app/main.py")]),
    ("services/agent_system/position_guard.py", [("prometheus_agents", "/app/position_guard.py")]),
    ("services/signal_engine/signal_validator.py", [("prometheus_signal", "/app/signal_validator.py")]),
    ("services/signal_engine/main.py", [("prometheus_signal", "/app/main.py")]),
    ("services/oms/main.py", [("prometheus_oms", "/app/main.py")]),
]

RESTART_SERVICES = ("shadow_system", "agent_system", "signal_engine", "oms", "immunity_system")

ENV_PATCH = """
grep -q '^MAX_POSITION_HOLD_SEC=' .env 2>/dev/null || echo 'MAX_POSITION_HOLD_SEC=3600' >> .env
grep -q '^STALE_VERDICT_HOLD_SEC=' .env 2>/dev/null || echo 'STALE_VERDICT_HOLD_SEC=1200' >> .env
grep -q '^SYMBOL_BLACKLIST=' .env 2>/dev/null || echo 'SYMBOL_BLACKLIST=ESPORTSUSDT,GTCUSDT,DEXEUSDT,AIOUSDT,BRUSDT,BEATUSDT,NAORISUSDT' >> .env
sed -i 's|^SHADOW_MIN_CONFIDENCE=.*|SHADOW_MIN_CONFIDENCE=0.60|' .env 2>/dev/null || true
sed -i 's|^PAPER_MIN_SIGNAL_CONFIDENCE=.*|PAPER_MIN_SIGNAL_CONFIDENCE=0.57|' .env 2>/dev/null || true
sed -i 's|^OMS_MIN_CONFIDENCE=.*|OMS_MIN_CONFIDENCE=0.58|' .env 2>/dev/null || true
sed -i 's|^SYMBOL_COOLDOWN_SEC=.*|SYMBOL_COOLDOWN_SEC=900|' .env 2>/dev/null || true
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

    prom_dir = s.get("VPS_PROJECT_DIR", "/root/prometheus")
    host = s.get("VPS_HOST", "194.163.181.39")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        s["VPS_HOST"], username=s.get("VPS_USER", "root"), password=s["VPS_PASS"],
        timeout=30, allow_agent=False, look_for_keys=False,
    )

    print("=" * 60)
    print("  HOT PATCH — build yok, docker cp + restart (~1-3 dk)")
    print("=" * 60)

    sftp = c.open_sftp()
    remote_tmp = "/tmp/prom_hot_patch"
    c.exec_command(f"mkdir -p {remote_tmp}")[1].read()

    copied = 0
    for rel, targets in PATCH_MAP:
        local = ROOT / rel
        if not local.exists():
            print(f"  ATLA (yok): {rel}")
            continue
        remote_file = f"{remote_tmp}/{local.name}"
        sftp.put(str(local), remote_file)
        # VPS git working tree — sonraki deploy cp+restart dogru dosyayi kullansin
        repo_dest = f"{prom_dir}/{rel.replace(chr(92), '/')}"
        try:
            sftp.put(str(local), repo_dest)
            print(f"  OK  {rel} -> repo")
        except OSError as exc:
            print(f"  UYARI repo yazilamadi ({repo_dest}): {exc}")
        for container, dest in targets:
            cmd = f"docker cp {remote_file} {container}:{dest}"
            _, o, e = c.exec_command(cmd, timeout=60)
            err = e.read().decode("utf-8", errors="replace").strip()
            if err and "Error" in err:
                print(f"  HATA {container}:{dest} — {err[:80]}")
            else:
                copied += 1
                print(f"  OK  {rel} -> {container}")
    sftp.close()

    print(f"\n  {copied} dosya kopyalandi")
    print("\n=== .env guncelleme ===")
    _, o, _ = c.exec_command(f"cd {prom_dir} && {ENV_PATCH}", timeout=30)
    print(o.read().decode("utf-8", errors="replace") or "  env OK")

    print("\n=== restart ===")
    svc_list = " ".join(RESTART_SERVICES)
    _, o, e = c.exec_command(
        f"cd {prom_dir} && docker compose restart {svc_list} 2>&1",
        timeout=180,
    )
    print(o.read().decode("utf-8", errors="replace") or e.read().decode("utf-8", errors="replace"))

    print("\n=== syntax dogrulama ===")
    for container in ("prometheus_signal", "prometheus_immunity"):
        _, o, e = c.exec_command(
            f"docker exec {container} python -m py_compile /app/risk_limits.py 2>&1",
            timeout=30,
        )
        out = (o.read() + e.read()).decode("utf-8", errors="replace").strip()
        print(f"  {container}: {'OK' if not out else out[:120]}")

    print("\n=== heartbeat (25 sn bekleniyor) ===")
    time.sleep(25)
    P = f"cd {prom_dir}; RP=$(grep '^REDIS_PASSWORD=' .env|cut -d= -f2-); "
    for svc in ("shadow_system", "agent_system", "signal_engine", "oms"):
        _, o, _ = c.exec_command(
            P + f'docker compose exec -T redis redis-cli -a "$RP" --no-auth-warning '
            f'GET "system:heartbeat:{svc}" 2>/dev/null',
            timeout=30,
        )
        ts = o.read().decode("utf-8", errors="replace").strip()
        print(f"  {svc}: {'OK' if ts and ts != '(nil)' else 'bekleniyor'}")

    print(f"\nBitti — http://{host}:3000/system")
    print("Karlilik: KARLILIK_TESHIS_DERIN.bat")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
