#!/usr/bin/env python3
"""
Prometheus VPS tam durum raporu — PowerShell'den:
  python scripts/vps_full_status.py
  veya:  .\\DURUM_KONTROL.ps1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "scripts" / ".deploy.secrets"

HB_SERVICES = [
    "data_ingestion",
    "feature_engine",
    "context_engine",
    "agent_system",
    "signal_engine",
    "learning_engine",
    "shadow_system",
    "immunity_system",
    "oms",
]
HB_OK_SEC = 120
HB_BOOTSTRAP_SEC = 300


def load_secrets() -> dict[str, str]:
    if not SECRETS.exists():
        print(f"HATA: {SECRETS} yok — copy scripts\\.deploy.secrets.example scripts\\.deploy.secrets")
        sys.exit(1)
    out: dict[str, str] = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    if not out.get("VPS_PASS"):
        print("HATA: VPS_PASS scripts/.deploy.secrets icinde gerekli")
        sys.exit(1)
    return out


def run(client, cmd: str, timeout: int = 120) -> str:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return out or err or "(bos)"


def section(title: str) -> None:
    print(f"\n{'=' * 62}\n  {title}\n{'=' * 62}")


def status_icon(ok: bool) -> str:
    return "OK" if ok else "SORUN"


def main() -> int:
    try:
        import paramiko
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
        import paramiko

    s = load_secrets()
    host = s.get("VPS_HOST", "194.163.181.39")
    user = s.get("VPS_USER", "root")
    prom_dir = s.get("VPS_PROJECT_DIR", "/root/prometheus")
    P = f"cd {prom_dir}; "

    print(f"\nPrometheus VPS Durum Raporu")
    print(f"Sunucu: {user}@{host}  |  Dizin: {prom_dir}")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(host, username=user, password=s["VPS_PASS"], timeout=30, allow_agent=False, look_for_keys=False)
    except Exception as exc:
        print(f"\nSSH HATA: {exc}")
        return 1

    # --- Konteynerler ---
    section("1. KONTEYNERLER")
    ps_raw = run(c, P + "docker compose ps -a --format '{{.Name}}|{{.Status}}' 2>/dev/null | sort")
    up, down = 0, 0
    problems: list[str] = []
    for line in ps_raw.splitlines():
        if "|" not in line:
            continue
        name, st = line.split("|", 1)
        name = name.strip()
        st = st.strip()
        bad = any(x in st.lower() for x in ("exit", "restart", "unhealthy", "created"))
        if bad:
            down += 1
            problems.append(f"  ! {name}: {st}")
            print(f"  ! {name}: {st}")
        else:
            up += 1
            print(f"  + {name}: {st}")
    print(f"\n  Ozet: {up} ayakta, {down} sorunlu")

    # --- Git / kod guncelligi ---
    section("2. KOD GUNCELLIGI (VPS git)")
    print(run(c, P + "git log -1 --oneline && git status -s | head -5"))
    local_hash = ""
    try:
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
        local_hash = r.stdout.strip()
    except Exception:
        pass
    remote_hash = run(c, P + "git rev-parse --short HEAD 2>/dev/null")
    if local_hash and remote_hash:
        sync = "SENKRON" if local_hash == remote_hash else f"FARKLI (PC={local_hash} VPS={remote_hash})"
        print(f"  PC vs VPS: {sync}")

    # --- Imaj heartbeat kodu ---
    section("3. IMJ GUNCELLIGI (heartbeat kodu konteynerde var mi?)")
    hb_grep = run(
        c,
        P + r"""for svc in data_ingestion feature_engine shadow_system immunity_system oms agent_system; do
  n=$(docker compose exec -T $svc grep -c "system:heartbeat" /app/main.py 2>/dev/null || echo 0)
  echo "$svc:$n"
done""",
    )
    stale_images: list[str] = []
    for line in hb_grep.splitlines():
        if ":" not in line:
            continue
        svc, cnt = line.strip().split(":", 1)
        cnt = cnt.strip()
        ok = cnt not in ("0", "")
        if not ok:
            stale_images.append(svc)
        print(f"  {'+' if ok else '!'} {svc}: heartbeat kodu {'var' if ok else 'YOK — rebuild gerekli'}")

    # --- Heartbeat ---
    section("4. SERVIS NABIZLARI (Redis heartbeat)")
    hb_raw = run(
        c,
        P + r"""RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-)
NOW=$(date +%s)
for svc in data_ingestion feature_engine context_engine agent_system signal_engine learning_engine shadow_system immunity_system oms; do
  TS=$(docker compose exec -T redis redis-cli -a "$RP" --no-auth-warning GET "system:heartbeat:$svc" 2>/dev/null|tr -d '\r')
  if [ -n "$TS" ] && [ "$TS" != "(nil)" ]; then
    AGE=$(python3 -c "print(int($NOW-float('$TS')))" 2>/dev/null)
    echo "$svc|$AGE"
  else
    echo "$svc|MISSING"
  fi
done""",
    )
    hb_problems: list[str] = []
    for line in hb_raw.splitlines():
        if "|" not in line:
            continue
        svc, val = line.strip().split("|", 1)
        if val == "MISSING":
            hb_problems.append(svc)
            print(f"  ! {svc}: NABIZ YOK")
        else:
            try:
                age = int(val)
            except ValueError:
                age = 999
            limit = HB_BOOTSTRAP_SEC if svc == "feature_engine" else HB_OK_SEC
            ok = age < limit
            if not ok:
                hb_problems.append(svc)
            print(f"  {'+' if ok else '!'} {svc}: {age}s once (limit {limit}s)")

    # --- Redis veri + trading ---
    section("5. VERI AKISI & TICARET")
    redis_block = run(
        c,
        P + r"""RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-)
RC="docker compose exec -T redis redis-cli -a $RP --no-auth-warning"
echo "DRY_RUN=$(grep '^DRY_RUN=' .env|cut -d= -f2-)"
echo "FEATURES=$($RC KEYS 'features:latest:*' 2>/dev/null|wc -l)"
echo "SIGNALS=$($RC KEYS 'signal:latest:*' 2>/dev/null|wc -l)"
echo "AGENTS=$($RC KEYS 'agents:verdict:*' 2>/dev/null|wc -l)"
echo "LEARN=$($RC KEYS 'learn:profile:*' 2>/dev/null|wc -l)"
echo "OMS_POS=$($RC KEYS 'oms:position:*' 2>/dev/null|wc -l)"
echo "SHADOW_POS=$($RC KEYS 'shadow:position:*' 2>/dev/null|wc -l)"
echo "ACTIVITY=$($RC LLEN activity:feed 2>/dev/null)"
echo "HALTED=$($RC GET system:trading:halted 2>/dev/null)"
echo "WS=$($RC GET ws:status 2>/dev/null|head -c 200)"
echo "---SHADOW_LB---"
$RC GET shadow:leaderboard 2>/dev/null|head -c 600
echo ""
echo "---PORTFOLIO---"
$RC GET portfolio:state:v1 2>/dev/null|head -c 500
echo ""
echo "---LLM---"
$RC GET system:llm:status 2>/dev/null|head -c 400
""",
        timeout=90,
    )
    for line in redis_block.splitlines():
        print(f"  {line}")

    # --- Son alim/satim ---
    section("6. SON ALIM / SATIM (log)")
    print(run(
        c,
        P + r"""docker compose logs oms shadow_system --tail 200 2>/dev/null \
| grep -iE 'open|close|buy|sell|fill|entry|reject|paper|shadow|position' \
| tail -20""",
    ))

    section("7. LLM & OGRENME")
    print(run(
        c,
        P + r"""docker compose logs learning_engine agent_system --tail 80 2>/dev/null \
| grep -iE 'lesson|learn|profile|ollama|llm|synth|debate|verdict|groq|openrouter' \
| tail -15""",
    ))

    section("8. DASHBOARD API")
    api = run(
        c,
        r"""for path in /api/status /api/system /api/signals /api/positions /api/llm/health; do
  code=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 8 http://localhost:3000$path 2>/dev/null || echo 000)
  echo "$path HTTP $code"
done""",
    )
    print(api)

    # --- Ozet ---
    section("OZET")
    issues: list[str] = []
    if down:
        issues.append(f"{down} konteyner sorunlu")
    if stale_images:
        issues.append(f"eski imaj (rebuild): {', '.join(stale_images)}")
    if hb_problems:
        issues.append(f"nabiz yok/stale: {', '.join(hb_problems)}")
    if local_hash and remote_hash and local_hash != remote_hash:
        issues.append("PC kodu VPS'e push edilmemis — PROMETHEUS_AYAGA_KALDIR.bat calistir")

    if issues:
        print("  SORUNLU:")
        for i in issues:
            print(f"    - {i}")
        print("\n  Cozum:")
        print("    PROMETHEUS_SKIP.bat          → hizli restart (~3 dk)")
        print("    PROMETHEUS_AYAGA_KALDIR.bat  → build + deploy (~10 dk)")
    else:
        print("  Tum kontroller gecti — sistem calisiyor gorunuyor.")

    print(f"\n  Dashboard: http://{host}:3000/system")
    print(f"  Signals:   http://{host}:3000/signals")
    print(f"  Positions: http://{host}:3000/positions")

    c.close()
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
