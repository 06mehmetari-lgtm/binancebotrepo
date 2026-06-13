#!/usr/bin/env python3
"""
Tek deploy — git push + akilli servis guncelleme + dashboard versiyon.

Kullanim: DEPLOY.bat
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"
VERSION_FILE = REPO / "deploy" / "VERSION.json"
REMOTE_SCRIPT = Path(__file__).resolve().parent / "smart_deploy_remote.py"
TIMING_FILE = Path(__file__).resolve().parent / ".deploy_timing.json"

# Sabit fazlar (sn) — gecmis ortalamadan bagimsiz
PHASE_GIT_S = 50
PHASE_SSH_S = 20
PHASE_PULL_S = 35
PHASE_VPS_OVERHEAD_S = 30

# Varsayilan servis sureleri (sn) — kotumser; gecmis veri ile iyilesir
DEFAULT_LIVE_CRITICAL_S = 150
DEFAULT_LIVE_NORMAL_S = 110
DEFAULT_BUILD_DASHBOARD_S = 2400
DEFAULT_HEAL_DOWN_S = 40
DEFAULT_HEAL_ONLY_S = 60
DEFAULT_FIRST_DEPLOY_S = 900

CRITICAL_SERVICES = frozenset({
    "data_ingestion", "feature_engine", "context_engine", "signal_engine",
    "agent_system", "shadow_system", "oms", "immunity_system",
})

SAFETY_MARGIN = 1.18
MIN_REMAINING_S = 15
AUTO_EXTEND_STEP_S = 60


def run_local(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd or REPO)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def fmt_duration(sec: float) -> str:
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def load_timing_history() -> dict:
    if not TIMING_FILE.exists():
        return {"services": {}, "totals": []}
    try:
        return json.loads(TIMING_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"services": {}, "totals": []}


def save_timing_history(history: dict) -> None:
    try:
        TIMING_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except OSError:
        pass


def _history_seconds(history: dict, key: str, default: int) -> int:
    samples = history.get("services", {}).get(key, {}).get("samples", [])
    if not samples:
        return default
    # Son 8 ornek — en kotu %90 + marj
    recent = samples[-8:]
    recent.sort()
    idx = min(len(recent) - 1, max(0, int(len(recent) * 0.9) - 1))
    return max(default, int(recent[idx] * SAFETY_MARGIN))


def record_timing(plan: dict, total_elapsed: float) -> None:
    history = load_timing_history()
    totals = history.setdefault("totals", [])
    totals.append(round(total_elapsed))
    history["totals"] = totals[-20:]

    per_service = max(45, total_elapsed / max(1, len(plan.get("update_live", [])) + len(plan.get("update_build", []))))
    services = history.setdefault("services", {})
    for svc in plan.get("update_live", []):
        key = f"live:{svc}"
        entry = services.setdefault(key, {"samples": []})
        entry["samples"] = (entry["samples"] + [int(per_service)])[-12:]
    for svc in plan.get("update_build", []):
        key = f"build:{svc}"
        entry = services.setdefault(key, {"samples": []})
        entry["samples"] = (entry["samples"] + [int(total_elapsed * 0.7)])[-8:]
    if plan.get("heal_down", 0) and not plan.get("update_live") and not plan.get("update_build"):
        entry = services.setdefault("heal_only", {"samples": []})
        entry["samples"] = (entry["samples"] + [int(total_elapsed)])[-12:]
    save_timing_history(history)


class DeployTimer:
    """Kendini ayarlayan geri sayim — erken 0:00 gostermez."""

    def __init__(self, estimate_sec: int) -> None:
        self.start = time.time()
        self.estimate = max(estimate_sec, 60)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._calibrated = False

    @property
    def total_est(self) -> int:
        return self.estimate

    def calibrate(self, total_from_start: int, source: str = "") -> None:
        elapsed = time.time() - self.start
        needed = max(total_from_start, int(elapsed + MIN_REMAINING_S + 45))
        if needed > self.estimate:
            self.estimate = needed
            self._calibrated = True
            if source:
                print(
                    f"\n  ⏱ Tahmin guncellendi: ~{fmt_duration(needed)} "
                    f"({source}, gecen {fmt_duration(elapsed)})"
                )

    def _auto_extend(self, elapsed: float) -> None:
        if elapsed + MIN_REMAINING_S >= self.estimate:
            extra = max(AUTO_EXTEND_STEP_S, int((elapsed - self.estimate) * 0.35) + AUTO_EXTEND_STEP_S)
            self.estimate += extra

    def _tick(self) -> None:
        while not self._stop.wait(1.0):
            elapsed = time.time() - self.start
            self._auto_extend(elapsed)
            remaining = max(MIN_REMAINING_S, self.estimate - elapsed)
            pct = min(97, int(elapsed / self.estimate * 100)) if self.estimate else 0
            overdue = elapsed > self.estimate * 0.95 and remaining <= MIN_REMAINING_S + 5
            remain_txt = "uzuyor…" if overdue else f"~{fmt_duration(remaining)}"
            line = (
                f"\r  ⏱ {fmt_duration(elapsed)} geçti"
                f" | kalan {remain_txt}"
                f" | %{pct}   "
            )
            sys.stdout.write(line)
            sys.stdout.flush()

    def start_tick(self) -> None:
        self._thread = threading.Thread(target=self._tick, daemon=True)
        self._thread.start()

    def stop(self) -> float:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        elapsed = time.time() - self.start
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()
        return elapsed


def pending_change_files() -> tuple[list[str], dict]:
    files: set[str] = set()
    for cmd in (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "diff", "--name-only", "--cached"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        _, out = run_local(cmd)
        files.update(ln.strip() for ln in out.splitlines() if ln.strip())
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        from smart_deploy_remote import filter_deploy_only_files, resolve_services  # noqa: WPS433

        filtered = filter_deploy_only_files(sorted(files))
        return filtered, resolve_services(filtered)
    except Exception:
        return sorted(files), {}


def plan_from_local(services: dict, history: dict | None = None) -> dict:
    history = history or load_timing_history()
    return {
        "update_live": sorted(s for s, i in services.items() if i.get("mode") != "build"),
        "update_build": sorted(s for s, i in services.items() if i.get("mode") == "build"),
        "heal_down": 0,
        "skipped": 0,
        "first_deploy": len(services) >= 10,
    }


def estimate_from_plan(plan: dict, history: dict | None = None) -> tuple[int, str]:
    history = history or load_timing_history()
    sec = PHASE_VPS_OVERHEAD_S
    parts: list[str] = []

    for svc in plan.get("update_live", []):
        default = DEFAULT_LIVE_CRITICAL_S if svc in CRITICAL_SERVICES else DEFAULT_LIVE_NORMAL_S
        sec += _history_seconds(history, f"live:{svc}", default)
        parts.append(f"{svc} cp+restart")

    for svc in plan.get("update_build", []):
        sec += _history_seconds(history, f"build:{svc}", DEFAULT_BUILD_DASHBOARD_S)
        parts.append(f"{svc} build (~{DEFAULT_BUILD_DASHBOARD_S // 60}dk+)")

    heal_down = int(plan.get("heal_down", 0) or 0)
    if heal_down:
        heal_each = _history_seconds(history, "heal_down", DEFAULT_HEAL_DOWN_S)
        sec += heal_down * heal_each
        parts.append(f"{heal_down} kapali heal")

    if not plan.get("update_live") and not plan.get("update_build"):
        sec += _history_seconds(history, "heal_only", DEFAULT_HEAL_ONLY_S)

    if plan.get("first_deploy"):
        sec = max(sec, DEFAULT_FIRST_DEPLOY_S)

    sec = int(sec * SAFETY_MARGIN)
    summary = ", ".join(parts[:4]) if parts else "minimal"
    if len(parts) > 4:
        summary += f" +{len(parts) - 4} daha"
    return sec, summary


def estimate_total_seconds(plan: dict, history: dict | None = None) -> tuple[int, str]:
    vps_sec, detail = estimate_from_plan(plan, history)
    total = PHASE_GIT_S + PHASE_SSH_S + PHASE_PULL_S + vps_sec
    return total, detail


def parse_deploy_plan(text: str) -> dict | None:
    for line in text.splitlines():
        if line.startswith("DEPLOY_PLAN:"):
            try:
                return json.loads(line.split(":", 1)[1].strip())
            except json.JSONDecodeError:
                return None
    m = re.search(r"DEPLOY_PLAN:\s*(\{.+?\})", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    return None


def git_push(version: str, short_sha: str) -> tuple[bool, str]:
    run_local(["git", "add", "-A"])
    _, status = run_local(["git", "status", "--porcelain"])
    if not status:
        _, cur = run_local(["git", "rev-parse", "--short", "HEAD"])
        return True, cur.splitlines()[-1] if cur else short_sha

    msg = f"deploy: v{version} ({short_sha})"
    code, out = run_local(["git", "commit", "-m", msg])
    if code != 0 and "nothing to commit" not in out.lower():
        return False, out

    code, out = run_local(["git", "push", "origin", "master"])
    if code != 0:
        run_local(["git", "pull", "origin", "master", "--rebase", "--no-edit"])
        code, out = run_local(["git", "push", "origin", "master"])
    return code == 0, out


def main() -> int:
    try:
        import paramiko
    except ImportError:
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
    history = load_timing_history()

    _, sha_full = run_local(["git", "rev-parse", "HEAD"])
    short_sha = sha_full.splitlines()[-1][:7] if sha_full else "0000000"
    version = datetime.now(timezone.utc).strftime("%Y%m%d.%H%M") + f"-{short_sha}"

    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(
        json.dumps({
            "version": version,
            "commit": short_sha,
            "deployed_at": datetime.now(timezone.utc).isoformat(),
            "note": "Otomatik deploy",
        }, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("=" * 68)
    print("  PROMETHEUS DEPLOY")
    print("=" * 68)
    print(f"  Versiyon: {version}")
    print()

    pending_files, affected = pending_change_files()
    local_plan = plan_from_local(affected, history)
    est_sec, est_detail = estimate_total_seconds(local_plan, history)
    print(f"  Tahmini sure: ~{fmt_duration(est_sec)} ({est_detail})")
    print("  (VPS plani gelince tahmin otomatik duzeltilir)")
    if pending_files:
        print(f"  Degisen dosya: {len(pending_files)}")
    if history.get("totals"):
        avg = int(sum(history["totals"][-5:]) / len(history["totals"][-5:]))
        print(f"  Son deploy ort.: ~{fmt_duration(avg)}")
    print()

    total_timer = DeployTimer(est_sec)
    total_timer.start_tick()
    deploy_plan: dict | None = None
    plan_applied = False

    print("[1/4] Git push...")
    t0 = time.time()
    ok, git_out = git_push(version, short_sha)
    if not ok:
        total_timer.stop()
        print(f"  HATA git: {git_out[:300]}")
        return 1
    print(f"  OK — {short_sha} ({fmt_duration(time.time() - t0)})")

    print("\n[2/4] VPS baglanti...")
    t0 = time.time()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(s["VPS_HOST"], username=s.get("VPS_USER", "root"), password=s["VPS_PASS"],
                  timeout=30, allow_agent=False, look_for_keys=False)
    except Exception as exc:
        total_timer.stop()
        print(f"  HATA SSH: {exc}")
        return 1
    print(f"  OK ({fmt_duration(time.time() - t0)})")

    print("\n[3/4] VPS git pull + script...")
    t0 = time.time()
    sftp = c.open_sftp()
    try:
        sftp.mkdir(f"{prom_dir}/scripts")
    except OSError:
        pass
    try:
        sftp.mkdir(f"{prom_dir}/deploy")
    except OSError:
        pass
    sftp.put(str(REMOTE_SCRIPT), f"{prom_dir}/scripts/smart_deploy_remote.py")
    sftp.put(str(VERSION_FILE), f"{prom_dir}/deploy/VERSION.json")
    sftp.close()

    _, o, e = c.exec_command(
        f"cd {prom_dir} && git pull origin master 2>&1 | tail -5",
        timeout=120,
    )
    pull_out = o.read().decode("utf-8", errors="replace")
    print(pull_out or e.read().decode("utf-8", errors="replace"))
    print(f"  OK ({fmt_duration(time.time() - t0)})")

    vps_only, _ = estimate_from_plan(local_plan, history)
    print(f"\n[4/4] Akilli deploy (on tahmin ~{fmt_duration(vps_only)})...")
    print("-" * 68)

    transport = c.get_transport()
    channel = transport.open_session() if transport else None
    if not channel:
        total_timer.stop()
        print("HATA: SSH channel")
        return 1
    channel.settimeout(3600)
    channel.exec_command(
        f"cd {prom_dir} && python3 -u scripts/smart_deploy_remote.py"
    )
    buf: list[str] = []
    deadline = time.time() + 3600
    while True:
        if channel.recv_ready():
            chunk = channel.recv(8192).decode("utf-8", errors="replace")
            if chunk:
                buf.append(chunk)
                if not plan_applied:
                    parsed = parse_deploy_plan("".join(buf))
                    if parsed:
                        deploy_plan = parsed
                        vps_est, vps_detail = estimate_total_seconds(parsed, history)
                        total_timer.calibrate(vps_est, f"VPS: {vps_detail}")
                        plan_applied = True
                sys.stdout.write(chunk)
                sys.stdout.flush()
        if channel.exit_status_ready():
            while channel.recv_ready():
                chunk = channel.recv(8192).decode("utf-8", errors="replace")
                if chunk:
                    buf.append(chunk)
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
            break
        if time.time() > deadline:
            total_timer.stop()
            print("\nHATA: Zaman asimi (60dk)")
            c.close()
            return 1
        time.sleep(0.05)

    out = "".join(buf)
    code = channel.recv_exit_status()
    c.close()

    total_elapsed = total_timer.stop()
    final_plan = deploy_plan or local_plan
    if "SMART_DEPLOY_DONE" in out or "SMART_DEPLOY_PARTIAL" in out:
        record_timing(final_plan, total_elapsed)

    final_est = total_timer.total_est
    accuracy = ""
    if final_est > 0:
        diff = total_elapsed - final_est
        if abs(diff) < 60:
            accuracy = "tahmin isabetli"
        elif diff > 0:
            accuracy = f"{fmt_duration(diff)} fazla surdu"
        else:
            accuracy = f"{fmt_duration(-diff)} erken bitti"

    print("\n" + "=" * 68)
    print(f"  Sure: {fmt_duration(total_elapsed)} (tahmin ~{fmt_duration(final_est)})")
    if accuracy:
        print(f"  Tahmin: {accuracy}")
    if "SMART_DEPLOY_DONE" in out:
        print(f"  BASARILI — Dashboard: v{version}")
        print("  Son deploy saati dashboard ustunde gorunur")
        print(f"  http://{host}:3000")
    elif "SMART_DEPLOY_PARTIAL" in out:
        print(f"  KISMI BASARI — v{version} (hatalar yukarida)")
        print(f"  http://{host}:3000")
    else:
        print("  HATA — loglari kontrol edin")
    print("=" * 68)
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
