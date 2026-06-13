#!/usr/bin/env python3
"""
Akilli deploy — VPS'te calisir.
Degisen dosyalara gore sadece ilgili servisleri gunceller.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROM_DIR = Path(os.environ.get("PROMETHEUS_DIR", "/root/prometheus"))
LAST_SHA_FILE = PROM_DIR / ".deploy_last_sha"
VERSION_FILE = PROM_DIR / "deploy" / "VERSION.json"
REDIS_CONTAINER = os.environ.get("REDIS_CONTAINER", "prometheus_redis")

# prefix veya dosya -> (compose_service, container, mode: live|build)
PATH_RULES: list[tuple[str, str, str, str]] = [
    ("services/data_ingestion/", "data_ingestion", "prometheus_data", "live"),
    ("services/sentiment/", "sentiment", "prometheus_sentiment", "live"),
    ("services/macro/", "macro", "prometheus_macro", "live"),
    ("services/feature_engine/", "feature_engine", "prometheus_features", "live"),
    ("services/context_engine/", "context_engine", "prometheus_context", "live"),
    ("services/learning_engine/", "learning_engine", "prometheus_learning", "live"),
    ("services/agent_system/", "agent_system", "prometheus_agents", "live"),
    ("services/signal_engine/", "signal_engine", "prometheus_signal", "live"),
    ("services/immunity_system/", "immunity_system", "prometheus_immunity", "live"),
    ("services/oms/", "oms", "prometheus_oms", "live"),
    ("services/shadow_system/", "shadow_system", "prometheus_shadow", "live"),
    ("services/autopsy/", "autopsy", "prometheus_autopsy", "live"),
    ("services/rag_memory/", "rag_memory", "prometheus_rag", "live"),
    ("services/neat_evolution/", "neat_evolution", "prometheus_neat", "live"),
    ("services/rl_agent/", "rl_agent", "prometheus_rl", "live"),
    ("services/scenario_engine/", "scenario_engine", "prometheus_scenarios", "live"),
    ("services/backtest/", "backtest", "prometheus_backtest", "live"),
    ("services/dashboard/", "dashboard", "prometheus_dashboard", "build"),
]

CONTAINER_BY_SERVICE: dict[str, str] = {
    "data_ingestion": "prometheus_data",
    "sentiment": "prometheus_sentiment",
    "macro": "prometheus_macro",
    "feature_engine": "prometheus_features",
    "context_engine": "prometheus_context",
    "learning_engine": "prometheus_learning",
    "agent_system": "prometheus_agents",
    "signal_engine": "prometheus_signal",
    "immunity_system": "prometheus_immunity",
    "oms": "prometheus_oms",
    "shadow_system": "prometheus_shadow",
    "autopsy": "prometheus_autopsy",
    "rag_memory": "prometheus_rag",
    "neat_evolution": "prometheus_neat",
    "rl_agent": "prometheus_rl",
    "scenario_engine": "prometheus_scenarios",
    "backtest": "prometheus_backtest",
    "dashboard": "prometheus_dashboard",
}

SHARED_FILE_TARGETS: dict[str, list[tuple[str, str]]] = {
    "services/shared/profit_rules.py": [
        ("shadow_system", "prometheus_shadow"),
        ("oms", "prometheus_oms"),
        ("agent_system", "prometheus_agents"),
        ("signal_engine", "prometheus_signal"),
        ("immunity_system", "prometheus_immunity"),
    ],
    "services/shared/risk_limits.py": [
        ("shadow_system", "prometheus_shadow"),
        ("oms", "prometheus_oms"),
        ("agent_system", "prometheus_agents"),
        ("signal_engine", "prometheus_signal"),
        ("immunity_system", "prometheus_immunity"),
    ],
    "services/shared/portfolio_try.py": [
        ("shadow_system", "prometheus_shadow"),
        ("oms", "prometheus_oms"),
    ],
    "services/shared/llm_providers.py": [
        ("agent_system", "prometheus_agents"),
        ("learning_engine", "prometheus_learning"),
    ],
    "services/shared/groq_orchestrator.py": [("agent_system", "prometheus_agents")],
    "services/shared/llm_status.py": [("agent_system", "prometheus_agents")],
    "services/shared/llm_runtime_keys.py": [("agent_system", "prometheus_agents")],
    "services/shared/llm_health.py": [("agent_system", "prometheus_agents")],
    "services/shared/proxy_pool.py": [("agent_system", "prometheus_agents")],
    "services/shared/position_plan.py": [("agent_system", "prometheus_agents")],
    "services/oms/portfolio_sync.py": [
        ("oms", "prometheus_oms"),
        ("shadow_system", "prometheus_shadow"),
    ],
}

LIVE_SRC: dict[str, str] = {
    "data_ingestion": "services/data_ingestion",
    "sentiment": "services/sentiment",
    "macro": "services/macro",
    "feature_engine": "services/feature_engine",
    "context_engine": "services/context_engine",
    "learning_engine": "services/learning_engine",
    "agent_system": "services/agent_system",
    "signal_engine": "services/signal_engine",
    "immunity_system": "services/immunity_system",
    "oms": "services/oms",
    "shadow_system": "services/shadow_system",
    "autopsy": "services/autopsy",
    "rag_memory": "services/rag_memory",
    "neat_evolution": "services/neat_evolution",
    "rl_agent": "services/rl_agent",
    "scenario_engine": "services/scenario_engine",
    "backtest": "services/backtest",
}

# Altyapi → veri → pipeline → diger (sira onemli)
STARTUP_WAVES: list[list[str]] = [
    ["redis", "postgres", "timescaledb", "qdrant"],
    ["data_ingestion", "feature_engine", "context_engine", "sentiment", "macro"],
    ["signal_engine", "agent_system", "learning_engine", "shadow_system", "oms", "immunity_system"],
    ["dashboard", "autopsy", "rag_memory", "neat_evolution", "rl_agent", "scenario_engine", "backtest"],
]

CRITICAL_SERVICES = frozenset({
    "data_ingestion", "feature_engine", "context_engine", "signal_engine",
    "agent_system", "shadow_system", "oms", "immunity_system",
})

INFRA_SERVICES = ["redis", "postgres", "timescaledb", "qdrant"]


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list[str] | str, timeout: int = 300) -> tuple[int, str]:
    if isinstance(cmd, str):
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=PROM_DIR)
    else:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=PROM_DIR)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out.strip()


def git_head() -> str:
    _, out = run(["git", "rev-parse", "HEAD"])
    return out.splitlines()[-1][:12] if out else "unknown"


DEPLOY_IGNORE_PREFIXES = (
    "deploy/",
    "scripts/smart_deploy",
    "scripts/.deploy",
    ".deploy_last_sha",
    "DEPLOY.bat",
    "HOT_PATCH.bat",
    "HIZLI_DEPLOY.bat",
    "KARLILIK_",
)


def filter_deploy_only_files(files: list[str]) -> list[str]:
    """Deploy script / versiyon dosyalari servis restart tetiklemesin."""
    out: list[str] = []
    for f in files:
        n = f.replace("\\", "/")
        if any(n.startswith(p) or n == p for p in DEPLOY_IGNORE_PREFIXES):
            continue
        if n.startswith("scripts/") and "smart_deploy" not in n:
            continue
        out.append(f)
    return out


def changed_files(old_sha: str, new_sha: str) -> list[str]:
    if not old_sha or old_sha == new_sha:
        return []
    code, out = run(["git", "diff", "--name-only", old_sha, new_sha])
    if code != 0:
        code2, out2 = run(["git", "diff", "--name-only", "HEAD~1", "HEAD"])
        return [ln.strip() for ln in out2.splitlines() if ln.strip()] if code2 == 0 else []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def resolve_services(files: list[str]) -> dict[str, dict]:
    """service -> {container, mode, reasons[]}"""
    found: dict[str, dict] = {}
    for f in files:
        f_norm = f.replace("\\", "/")
        if f_norm in SHARED_FILE_TARGETS:
            for svc, ctr in SHARED_FILE_TARGETS[f_norm]:
                found.setdefault(svc, {"container": ctr, "mode": "live", "reasons": []})
                found[svc]["reasons"].append(f_norm)
            continue
        for prefix, svc, ctr, mode in PATH_RULES:
            if f_norm.startswith(prefix) or f_norm == prefix.rstrip("/"):
                found.setdefault(svc, {"container": ctr, "mode": mode, "reasons": []})
                found[svc]["reasons"].append(f_norm)
                if mode == "build":
                    found[svc]["mode"] = "build"
                break
    return found


def container_running(name: str) -> bool:
    code, out = run(f"docker ps --format '{{{{.Names}}}}' | grep -qx '{name}' && echo yes || echo no")
    return "yes" in out


def container_state(name: str) -> str:
    """running | exited | missing | restarting | other"""
    code, out = run(
        f"docker inspect --format '{{{{.State.Status}}}}' {name} 2>/dev/null || echo missing"
    )
    st = (out.splitlines()[-1] if out else "missing").strip().lower()
    return st if st in ("running", "exited", "restarting", "created", "paused", "missing") else "other"


def scan_fleet() -> list[dict]:
    """Tum bilinen servislerin durumu."""
    rows: list[dict] = []
    for svc, ctr in CONTAINER_BY_SERVICE.items():
        st = container_state(ctr)
        rows.append({
            "service": svc,
            "container": ctr,
            "status": st,
            "up": st == "running",
            "critical": svc in CRITICAL_SERVICES,
        })
    return rows


def heartbeat_age(svc: str) -> int | None:
    """Redis heartbeat yasi (sn); yoksa None."""
    rp = redis_pw()
    if not rp:
        return None
    code, out = run([
        "docker", "exec", REDIS_CONTAINER,
        "redis-cli", "-a", rp, "--no-auth-warning",
        "GET", f"system:heartbeat:{svc}",
    ], timeout=15)
    if code != 0 or not out or out == "(nil)":
        return None
    try:
        ts = float(out.splitlines()[-1].strip())
        return max(0, int(time.time() - ts))
    except (TypeError, ValueError):
        return None


def up_service(svc: str) -> tuple[bool, str]:
    code, out = run(f"docker compose up -d {svc} 2>&1", timeout=180)
    return code == 0, out[:250]


def heal_fleet(
    code_affected: set[str] | None = None,
    heal_all_down: bool = True,
) -> tuple[list[dict], list[dict]]:
    """
    Sadece KAPALI servisleri kaldirir.
    - Ayaktaki servislere DOKUNMAZ (zaman kazanmak icin)
    - code_affected: kod degisen ama kapali olanlar once siraya alinir
    """
    healed: list[dict] = []
    failed: list[dict] = []
    fleet = scan_fleet()
    code_affected = code_affected or set()

    to_fix: list[str] = []
    for r in fleet:
        if r["up"]:
            continue
        svc = r["service"]
        # Kapali → kesin kaldır (kritik + kod etkilenen + diger down)
        if r["critical"] or svc in code_affected or heal_all_down:
            if svc not in to_fix:
                to_fix.append(svc)

    # Kod etkilenen ama kapali — oncelik sirasina gore one al
    ordered: list[str] = []
    for wave in STARTUP_WAVES:
        for svc in wave:
            if svc in to_fix and svc not in ordered:
                ordered.append(svc)
    for svc in to_fix:
        if svc not in ordered:
            ordered.append(svc)
    to_fix = ordered

    if not to_fix:
        return healed, failed

    # Altyapi kapaliysa once onu kaldir
    for svc in INFRA_SERVICES:
        code, out = run(
            f"docker compose ps --format '{{{{.Service}}}}' --filter status=running "
            f"2>/dev/null | grep -qx '{svc}' && echo up || echo down"
        )
        if "down" in out:
            log(f"    ↑ altyapi {svc} (kapali)")
            ok, msg = up_service(svc)
            if ok:
                healed.append({"service": svc, "action": "infra_up"})
            else:
                failed.append({"service": svc, "error": msg, "action": "infra_up"})
    if healed:
        time.sleep(2)

    log("\n  KAPALI → KALDIRILIYOR (ayaktakilere dokunulmuyor):")
    for svc in to_fix:
        ctr = CONTAINER_BY_SERVICE.get(svc, "?")
        st = container_state(ctr)
        if st == "running":
            continue
        why = "kod etkilendi" if svc in code_affected else ("kritik" if svc in CRITICAL_SERVICES else "kapali")
        log(f"    ↑ {svc} ({ctr}) [{why}]")
        ok, msg = up_service(svc)
        if ok:
            time.sleep(3 if svc in CRITICAL_SERVICES else 1)
            healed.append({"service": svc, "container": ctr, "was": st, "action": "up -d"})
        else:
            failed.append({"service": svc, "container": ctr, "was": st, "error": msg})

    return healed, failed


def redis_pw() -> str:
    for line in (PROM_DIR / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("REDIS_PASSWORD="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def shas_match(a: str, b: str) -> bool:
    x, y = a.strip().lower(), b.strip().lower()
    if not x or not y:
        return False
    if x == y:
        return True
    short, long = (x, y) if len(x) <= len(y) else (y, x)
    return long.startswith(short)


def deploy_env() -> tuple[str, list[str]]:
    expected = os.environ.get("DEPLOY_EXPECTED_SHA", "").strip()
    raw = os.environ.get("DEPLOY_PC_FILES", "[]").strip()
    try:
        pc_files = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        pc_files = []
    if not isinstance(pc_files, list):
        pc_files = []
    return expected, pc_files


def build_deploy_record(
    *,
    version_meta: dict,
    new_sha: str,
    files: list[str],
    deploy_plan: dict,
    ok_list: list[dict],
    fail_list: list[dict],
    skipped: list[str],
    fleet_summary: dict,
    healed: list[dict] | None = None,
) -> dict:
    expected, pc_files = deploy_env()
    git_sync_ok = shas_match(new_sha, expected) if expected else True
    applied = [
        x["service"] for x in ok_list
        if x.get("action") in ("live_cp+restart", "build+up")
    ]
    code_applied = bool(applied)

    if not git_sync_ok:
        status = "sync_failed"
    elif code_applied:
        status = "partial" if fail_list else "ok"
    elif files:
        status = "no_apply"
    else:
        status = "no_changes"
    if fleet_summary.get("down_services") and status == "ok":
        status = "partial"

    if not git_sync_ok:
        summary_tr = (
            f"Kod yansimadi: VPS git ({new_sha[:12]}) ile beklenen ({expected[:12]}) eslesmiyor"
        )
    elif code_applied:
        summary_tr = f"Guncellenen: {', '.join(applied)}"
    elif files:
        summary_tr = "Dosya degisti ama hicbir servis guncellenemedi"
    elif pc_files:
        summary_tr = (
            f"PC'de {len(pc_files)} dosya vardi; VPS'te ayni commit — servis guncellenmedi"
        )
    else:
        summary_tr = "Kod degismedi — servisler ayakta birakildi"

    return {
        "version": version_meta.get("version", new_sha),
        "commit": version_meta.get("commit", new_sha),
        "commit_short": new_sha,
        "deployed_at": time.time(),
        "deployed_at_iso": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "files_changed": files,
        "pc_files_pending": pc_files,
        "services_ok": [x["service"] for x in ok_list],
        "services_failed": [x.get("service", "?") for x in fail_list],
        "details_ok": ok_list,
        "details_failed": fail_list,
        "skipped": skipped,
        "plan": deploy_plan,
        "fleet": fleet_summary,
        "code_applied": code_applied,
        "git_sync_ok": git_sync_ok,
        "vps_sha": new_sha,
        "expected_sha": expected or new_sha,
        "summary_tr": summary_tr,
        "status": status,
    }


def redis_set(key: str, payload: dict) -> None:
    rp = redis_pw()
    if not rp:
        return
    data = json.dumps(payload, ensure_ascii=False)
    run([
        "docker", "exec", REDIS_CONTAINER,
        "redis-cli", "-a", rp, "--no-auth-warning",
        "SET", key, data, "EX", "604800",
    ], timeout=30)


def live_update(svc: str, container: str, reasons: list[str]) -> tuple[bool, str]:
    src = LIVE_SRC.get(svc)
    if not src:
        return False, f"kaynak dizin yok: {svc}"
    src_path = PROM_DIR / src
    if not src_path.is_dir():
        return False, f"dizin bulunamadi: {src}"
    if not container_running(container):
        ok, msg = up_service(svc)
        if not ok:
            return False, f"container down, up basarisiz: {msg[:120]}"
        time.sleep(3)
        if not container_running(container):
            return False, f"container hala down: {container}"
    code, out = run(["docker", "cp", f"{src_path}/.", f"{container}:/app/"])
    if code != 0:
        return False, out[:200]
    for reason in reasons:
        if reason in SHARED_FILE_TARGETS:
            for _, ctr in SHARED_FILE_TARGETS[reason]:
                if ctr == container:
                    src_file = PROM_DIR / reason
                    if src_file.is_file():
                        run(["docker", "cp", str(src_file), f"{container}:/app/{src_file.name}"])
    if svc == "oms" and (PROM_DIR / "services/oms/portfolio_sync.py").is_file():
        run(["docker", "cp", str(PROM_DIR / "services/oms/portfolio_sync.py"), f"{container}:/app/portfolio_sync.py"])
    if svc == "shadow_system":
        run(["docker", "cp", str(PROM_DIR / "services/oms/portfolio_sync.py"), f"{container}:/app/portfolio_sync.py"])
        for shared in ("profit_rules.py", "risk_limits.py", "portfolio_try.py"):
            sf = PROM_DIR / "services/shared" / shared
            if sf.is_file():
                run(["docker", "cp", str(sf), f"{container}:/app/{shared}"])
    if svc == "agent_system":
        for shared in ("profit_rules.py", "risk_limits.py", "llm_providers.py", "groq_orchestrator.py",
                       "llm_status.py", "llm_runtime_keys.py", "llm_health.py", "proxy_pool.py", "position_plan.py"):
            sf = PROM_DIR / "services/shared" / shared
            if sf.is_file():
                run(["docker", "cp", str(sf), f"{container}:/app/{shared}"])
    return True, "docker cp OK"


def build_service(svc: str) -> tuple[bool, str]:
    code, out = run(f"docker compose build {svc} 2>&1 | tail -15", timeout=1800)
    if code != 0:
        return False, out[:300]
    code2, out2 = run(f"docker compose up -d {svc} 2>&1", timeout=120)
    return code2 == 0, (out + "\n" + out2)[:300]


def apply_running_updates(
    services: dict[str, dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Sadece KOD ETKİLENEN servisler:
    - Ayakta + live  → docker cp + restart
    - Ayakta + build → docker compose build + up
    - Kapali         → heal_fleet halletti; burada cp + restart (yeni kod)
    Ayakta + kod etkilenmiyor → bu fonksiyona HIC GIRMEZ.
    """
    ok_list: list[dict] = []
    fail_list: list[dict] = []
    skipped_up: list[dict] = []

    for svc, info in sorted(services.items()):
        ctr = info["container"]
        mode = info["mode"]
        reasons = info.get("reasons", [])
        running = container_running(ctr)

        if not running:
            log(f"    ↑ {svc} kapali — once up, sonra kod yukle")
            up_ok, up_msg = up_service(svc)
            if not up_ok:
                fail_list.append({"service": svc, "action": "up", "error": up_msg})
                continue
            time.sleep(3 if svc in CRITICAL_SERVICES else 1)
            running = container_running(ctr)

        if mode == "build":
            log(f"    ■ {svc} BUILD (kod degisti, ayakta={running})")
            success, msg = build_service(svc)
            if success:
                ok_list.append({"service": svc, "action": "build+up", "why": reasons[:2]})
            else:
                fail_list.append({"service": svc, "action": "build", "error": msg})
            continue

        if not running:
            fail_list.append({"service": svc, "action": "live_cp", "error": "container ayaga kalkmadi"})
            continue

        log(f"    ↻ {svc} cp+restart (kod degisti)")
        success, msg = live_update(svc, ctr, reasons)
        if not success:
            fail_list.append({"service": svc, "action": "live_cp", "error": msg})
            continue
        r_ok, r_msg = restart_service(svc)
        if r_ok:
            ok_list.append({
                "service": svc, "action": "live_cp+restart",
                "why": reasons[:2], "msg": msg,
            })
        else:
            fail_list.append({"service": svc, "action": "restart", "error": r_msg})

    return ok_list, fail_list, skipped_up


def restart_service(svc: str) -> tuple[bool, str]:
    code, out = run(f"docker compose restart {svc} 2>&1", timeout=120)
    return code == 0, out[:200]


def main() -> int:
    os.chdir(PROM_DIR)
    log("=" * 68)
    log("  AKILLI DEPLOY — durum tarama + degisen servisler")
    log("=" * 68)

    # ── 0) Fleet durumu ───────────────────────────
    fleet_before = scan_fleet()
    up_n = sum(1 for r in fleet_before if r["up"])
    down_n = len(fleet_before) - up_n
    log(f"\n[0] SUNUCU DURUMU — {up_n} ayakta / {down_n} kapali")
    for r in fleet_before:
        if r["up"]:
            hb = heartbeat_age(r["service"]) if r["service"] in CRITICAL_SERVICES else None
            hb_s = f" heartbeat={hb}s" if hb is not None else ""
            log(f"    ✓ {r['service']:18s} {r['container']}{hb_s}")
        else:
            mark = "!" if r["critical"] else " "
            log(f"    {mark}✗ {r['service']:18s} {r['container']}  [{r['status']}]")

    new_sha = git_head()
    old_sha = LAST_SHA_FILE.read_text(encoding="utf-8").strip() if LAST_SHA_FILE.exists() else ""

    version_meta: dict = {}
    if VERSION_FILE.exists():
        try:
            version_meta = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    raw_files = changed_files(old_sha, new_sha)
    files = filter_deploy_only_files(raw_files)
    if raw_files and len(files) < len(raw_files):
        log(f"  Deploy-only dosyalar atlandi ({len(raw_files) - len(files)} adet)")
    if not files and not old_sha:
        log("  Ilk deploy — tum pipeline servisleri")
        services = {
            svc: {"container": CONTAINER_BY_SERVICE[svc], "mode": "live", "reasons": ["ilk_deploy"]}
            for svc in LIVE_SRC
        }
    elif not files:
        log("  Degisen dosya yok — versiyon kaydi guncelleniyor")
        services = {}
    else:
        services = resolve_services(files)

    log(f"\n  Onceki SHA: {old_sha[:12] or '(yok)'}")
    log(f"  Yeni SHA:   {new_sha}")
    log(f"  Versiyon:   {version_meta.get('version', '?')}")
    log(f"  Degisen:    {len(files)} dosya")

    if files:
        log("\n  Dosyalar:")
        for f in files[:30]:
            log(f"    - {f}")
        if len(files) > 30:
            log(f"    ... +{len(files)-30} daha")

    affected_set = set(services.keys())
    deploy_plan = {
        "update_live": sorted(s for s, i in services.items() if i.get("mode") != "build"),
        "update_build": sorted(s for s, i in services.items() if i.get("mode") == "build"),
        "heal_down": down_n,
        "skipped": sum(1 for r in fleet_before if r["up"] and r["service"] not in affected_set),
        "first_deploy": (not old_sha) and bool(services),
    }
    log(f"DEPLOY_PLAN: {json.dumps(deploy_plan, separators=(',', ':'))}")

    ok_list: list[dict] = []
    fail_list: list[dict] = []

    # ── 1) Kapali servisleri kaldir (ayaktakilere dokunma) ──
    healed, heal_failed = heal_fleet(affected_set)
    if healed:
        log(f"\n  Kaldirilan (kapaliydi): {len(healed)} servis")
        ok_list.extend([{**h, "action": h.get("action", "heal_up")} for h in healed])
    if heal_failed:
        fail_list.extend([{**h, "action": "heal_up"} for h in heal_failed])

    # ── 2) Ayakta + kod degismedi → ATLA ──
    skipped: list[str] = []
    for r in fleet_before:
        if r["up"] and r["service"] not in affected_set:
            skipped.append(r["service"])
    if skipped:
        log(f"\n  ATLANDI ({len(skipped)} servis — ayakta, kod degismedi):")
        for svc in skipped[:12]:
            log(f"    = {svc}")
        if len(skipped) > 12:
            log(f"    ... +{len(skipped) - 12} daha")

    log("\n  GUNCELLENECEK (kod degisti):")
    if not services:
        log("    (dosya degismedi — sadece kapali servisler kaldirilacak)")
        fleet_after = scan_fleet()
        deploy_record = build_deploy_record(
            version_meta=version_meta,
            new_sha=new_sha,
            files=files,
            deploy_plan=deploy_plan,
            ok_list=[{**h, "service": h["service"]} for h in healed],
            fail_list=[{**h, "service": h.get("service", "?")} for h in heal_failed],
            skipped=skipped,
            fleet_summary={
                "before_up": up_n, "before_down": down_n,
                "after_up": sum(1 for r in fleet_after if r["up"]),
                "down_services": [r["service"] for r in fleet_after if not r["up"]],
            },
            healed=healed,
        )
        deploy_record["note"] = "kod degismedi, fleet heal"
        redis_set("system:deploy:version", deploy_record)
        log(f"\n  {deploy_record.get('summary_tr', '')}")
        LAST_SHA_FILE.write_text(new_sha, encoding="utf-8")
        if heal_failed:
            log("\n  YAPILAMAYANLAR:")
            for x in heal_failed:
                log(f"    ✗ {x.get('service','?')} — {x.get('error','')[:120]}")
            log("\nSMART_DEPLOY_PARTIAL")
            return 1
        log("\nSMART_DEPLOY_DONE")
        return 0

    for svc, info in sorted(services.items()):
        reasons = ", ".join(info["reasons"][:2])
        ctr = info["container"]
        st = "ayakta" if container_running(ctr) else "kapali→up"
        log(f"    • {svc} [{info['mode']}] {st}  ({reasons})")

    log("\n  KOD GUNCELLEME (sadece yukaridaki liste):")
    upd_ok, upd_fail, _ = apply_running_updates(services)
    ok_list.extend(upd_ok)
    fail_list.extend(upd_fail)

    # ── Son durum + heartbeat ─────────────────────
    log("\n[SON] Heartbeat kontrol (kritik servisler):")
    hb_ok: list[str] = []
    hb_wait: list[str] = []
    time.sleep(8)
    for svc in CRITICAL_SERVICES:
        age = heartbeat_age(svc)
        if age is not None and age < 120:
            log(f"    ✓ {svc} heartbeat {age}s")
            hb_ok.append(svc)
        else:
            log(f"    ? {svc} heartbeat bekleniyor" + (f" ({age}s)" if age else ""))
            hb_wait.append(svc)

    fleet_after = scan_fleet()
    fleet_summary = {
        "before_up": up_n,
        "before_down": down_n,
        "after_up": sum(1 for r in fleet_after if r["up"]),
        "after_down": sum(1 for r in fleet_after if not r["up"]),
        "down_services": [r["service"] for r in fleet_after if not r["up"]],
        "heartbeat_ok": hb_ok,
        "heartbeat_wait": hb_wait,
    }

    deploy_record = build_deploy_record(
        version_meta=version_meta,
        new_sha=new_sha,
        files=files,
        deploy_plan=deploy_plan,
        ok_list=ok_list,
        fail_list=fail_list,
        skipped=skipped,
        fleet_summary=fleet_summary,
    )
    if fleet_summary["down_services"] and deploy_record["status"] == "ok":
        deploy_record["status"] = "partial"
    redis_set("system:deploy:version", deploy_record)
    LAST_SHA_FILE.write_text(new_sha, encoding="utf-8")

    log("\n" + "=" * 68)
    log(f"  DEPLOY {deploy_record['status'].upper()} — v{deploy_record['version']}")
    log(f"  {deploy_record.get('summary_tr', '')}")
    log("=" * 68)

    if ok_list:
        log("\n  BASARILI:")
        for x in ok_list:
            log(f"    ✓ {x['service']} ({x.get('action','')})")

    if fail_list:
        log("\n  YAPILAMAYANLAR:")
        for x in fail_list:
            log(f"    ✗ {x.get('service','?')} — {x.get('error', x.get('action',''))[:120]}")

    still_down = fleet_summary["down_services"]
    if still_down:
        log("\n  HALA KAPALI:")
        for svc in still_down:
            ctr = CONTAINER_BY_SERVICE.get(svc, "?")
            log(f"    ✗ {svc} ({ctr})")

    if fail_list or still_down:
        log("\nSMART_DEPLOY_PARTIAL")
        return 1

    log("\nSMART_DEPLOY_DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
