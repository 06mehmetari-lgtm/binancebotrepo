#!/usr/bin/env python3
"""
Postgres SQL migration runner — deploy sirasinda otomatik calisir.

Kullanim (VPS):
  python3 scripts/run_postgres_migrations.py

Idempotent: schema_migrations tablosunda kayitli dosyalar atlanir.
003_max_open_30.sql gibi guncellemeler bir kez uygulanir; Redis risk limitleri senkronize edilir.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROM_DIR = Path(os.environ.get("PROMETHEUS_DIR", Path(__file__).resolve().parent.parent))
MIGRATIONS_DIR = PROM_DIR / "infrastructure" / "postgres" / "migrations"
DB_NAME = os.environ.get("POSTGRES_DB", "prometheus_trading")
PG_USER = os.environ.get("POSTGRES_USER", "prometheus")
PG_CONTAINER = os.environ.get("POSTGRES_CONTAINER", "prometheus_postgres")
REDIS_CONTAINER = os.environ.get("REDIS_CONTAINER", "prometheus_redis")

RISK_SYNC_SERVICES = ("immunity_system", "signal_engine", "oms", "shadow_system")


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: str | list[str], timeout: int = 120) -> tuple[int, str]:
    if isinstance(cmd, str):
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=PROM_DIR)
    else:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=PROM_DIR)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def read_env(key: str, default: str = "") -> str:
    env_path = PROM_DIR / ".env"
    if not env_path.exists():
        return default
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


def postgres_running() -> bool:
    code, out = run(
        f"docker ps --format '{{{{.Names}}}}' | grep -qx '{PG_CONTAINER}' && echo yes || echo no"
    )
    return "yes" in out


def ensure_postgres() -> tuple[bool, str]:
    if postgres_running():
        return True, "postgres ayakta"
    log("  postgres kapali — docker compose up -d postgres")
    code, out = run("docker compose up -d postgres 2>&1", timeout=180)
    if code != 0:
        return False, out[:300]
    for _ in range(30):
        code2, out2 = run(
            f"docker compose exec -T postgres pg_isready -U {PG_USER} -d {DB_NAME} 2>&1"
        )
        if code2 == 0:
            return True, "postgres hazir"
        run("sleep 2")
    return False, "postgres hazir degil (timeout)"


def psql(sql: str, *, file: Path | None = None) -> tuple[int, str]:
    if file:
        cmd = f"docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U {PG_USER} -d {DB_NAME} -f -"
        r = subprocess.run(
            cmd,
            shell=True,
            input=file.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            timeout=120,
            cwd=PROM_DIR,
        )
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    cmd = [
        "docker", "compose", "exec", "-T", "postgres",
        "psql", "-v", "ON_ERROR_STOP=1", "-U", PG_USER, "-d", DB_NAME, "-c", sql,
    ]
    return run(cmd)


def ensure_migrations_table() -> tuple[bool, str]:
    sql = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        filename   VARCHAR(128) PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
    code, out = psql(sql)
    return code == 0, out[:300]


def applied_migrations() -> set[str]:
    code, out = psql(
        "SELECT filename FROM schema_migrations ORDER BY filename;"
    )
    if code != 0:
        return set()
    names: set[str] = set()
    for line in out.splitlines():
        line = line.strip()
        if line and not line.startswith("(") and line != "filename" and not line.startswith("-") and line != "filename":
            if ".sql" in line:
                names.add(line)
    # psql -t -A daha temiz; fallback parse
    code2, out2 = run(
        f"docker compose exec -T postgres psql -U {PG_USER} -d {DB_NAME} -t -A -c "
        f"\"SELECT filename FROM schema_migrations;\""
    )
    if code2 == 0:
        names = {ln.strip() for ln in out2.splitlines() if ln.strip()}
    return names


def record_migration(filename: str) -> None:
    safe = filename.replace("'", "''")
    psql(f"INSERT INTO schema_migrations (filename) VALUES ('{safe}') ON CONFLICT DO NOTHING;")


def sync_risk_limits_redis() -> tuple[bool, str]:
    pw = read_env("REDIS_PASSWORD", "")
    auth = f"-a {pw} " if pw else ""
    code, out = run(
        f"docker compose exec -T postgres psql -U {PG_USER} -d {DB_NAME} -t -A -c "
        "\"SELECT row_to_json(t)::text FROM ("
        "SELECT max_leverage, max_position_pct, max_daily_loss_pct, max_open_positions,"
        " min_signal_confidence, min_immunity_confidence, max_trades_per_day,"
        " EXTRACT(EPOCH FROM updated_at) AS updated_at, updated_by"
        " FROM system_risk_limits WHERE id = 1) t;\""
    )
    if code != 0 or not out.strip():
        return False, out[:200] or "risk_limits bos"
    row = out.splitlines()[-1].strip()
    try:
        json.loads(row)
    except json.JSONDecodeError:
        return False, "risk_limits JSON parse hatasi"
    esc = row.replace("'", "'\"'\"'")
    run(
        f"docker compose exec -T redis redis-cli {auth}SET system:risk_limits:v1 '{esc}' >/dev/null"
    )
    run(
        f"docker compose exec -T redis redis-cli {auth}PUBLISH ch:risk_limits:updated '{esc}' >/dev/null"
    )
    return True, f"max_open={json.loads(row).get('max_open_positions', '?')}"


def restart_risk_services() -> None:
    svc_list = " ".join(RISK_SYNC_SERVICES)
    run(f"docker compose restart {svc_list} 2>&1", timeout=180)


def main() -> int:
    global PG_USER, DB_NAME
    PG_USER = read_env("POSTGRES_USER", PG_USER)
    DB_NAME = read_env("POSTGRES_DB", DB_NAME)

    ok, msg = ensure_postgres()
    if not ok:
        log(f"MIGRATIONS_FAIL: postgres — {msg}")
        return 1

    ok, msg = ensure_migrations_table()
    if not ok:
        log(f"MIGRATIONS_FAIL: schema_migrations — {msg}")
        return 1

    if not MIGRATIONS_DIR.is_dir():
        log("MIGRATIONS_OK: klasor yok, atlandi")
        return 0

    done = applied_migrations()
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    applied: list[str] = []
    risk_touch = False

    for path in files:
        name = path.name
        if name in done:
            continue
        log(f"  → migration: {name}")
        code, out = psql("", file=path)
        if code != 0:
            log(f"MIGRATIONS_FAIL: {name} — {out[-400:]}")
            return 1
        record_migration(name)
        applied.append(name)
        if "risk" in name.lower() or "max_open" in name.lower():
            risk_touch = True

    if applied:
        log(f"MIGRATIONS_APPLIED: {','.join(applied)}")
        if risk_touch or any("max_open" in a for a in applied):
            s_ok, s_msg = sync_risk_limits_redis()
            if s_ok:
                log(f"  Redis risk_limits senkron: {s_msg}")
                restart_risk_services()
                log(f"  Yeniden baslatildi: {', '.join(RISK_SYNC_SERVICES)}")
            else:
                log(f"  UYARI: Redis sync basarisiz — {s_msg}")
    else:
        log("MIGRATIONS_OK: yeni migration yok")

    return 0


if __name__ == "__main__":
    sys.exit(main())
