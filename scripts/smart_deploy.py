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


class DeployProgressTimer:
    """Faz bazli ilerleme — yuzde ve kalan sure gercek asamaya gore."""

    def __init__(self, plan: dict, history: dict) -> None:
        self.start = time.time()
        self.history = history
        self.plan = plan
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.phase_done: set[str] = set()
        self.current_phase = "prep"
        self.phase_started = time.time()
        self.build_frac = 0.0
        self.build_label = ""
        self._budgets = self._calc_budgets(plan)
        self._floor_pct = 0

    def _calc_budgets(self, plan: dict) -> dict[str, int]:
        budgets: dict[str, int] = {
            "prep": PHASE_GIT_S + PHASE_SSH_S + PHASE_PULL_S,
            "fleet": 55,
            "finish": 20,
        }
        for svc in plan.get("update_live", []):
            default = DEFAULT_LIVE_CRITICAL_S if svc in CRITICAL_SERVICES else DEFAULT_LIVE_NORMAL_S
            budgets[f"live:{svc}"] = _history_seconds(self.history, f"live:{svc}", default)
        for svc in plan.get("update_build", []):
            budgets["build"] = _history_seconds(self.history, f"build:{svc}", DEFAULT_BUILD_DASHBOARD_S)
        heal = int(plan.get("heal_down", 0) or 0)
        if heal:
            budgets["heal"] = heal * _history_seconds(self.history, "heal_down", DEFAULT_HEAL_DOWN_S)
        if not plan.get("update_live") and not plan.get("update_build"):
            budgets["idle"] = _history_seconds(self.history, "heal_only", DEFAULT_HEAL_ONLY_S)
        if plan.get("first_deploy"):
            budgets["build"] = max(budgets.get("build", 0), DEFAULT_FIRST_DEPLOY_S)
        return budgets

    @property
    def total_budget(self) -> int:
        raw = sum(self._budgets.values())
        return max(60, int(raw * SAFETY_MARGIN))

    def set_plan(self, plan: dict, source: str = "") -> None:
        self._floor_pct = self.progress_pct()
        self.plan = plan
        self._budgets = self._calc_budgets(plan)
        if source:
            elapsed = time.time() - self.start
            print(
                f"\n  ⏱ Plan: ~{fmt_duration(self.total_budget)} toplam "
                f"({source}, gecen {fmt_duration(elapsed)})"
            )

    def mark_done(self, phase: str, next_phase: str | None = None) -> None:
        self.phase_done.add(phase)
        if next_phase:
            self.current_phase = next_phase
            self.phase_started = time.time()

    def on_output(self, chunk: str) -> None:
        if "[0] SUNUCU DURUMU" in chunk:
            self.mark_done("prep", "fleet")
        if "DEPLOY_PLAN:" in chunk:
            parsed = parse_deploy_plan(chunk)
            if parsed:
                self.set_plan(parsed, "VPS plani")
                self.mark_done("fleet", "work")
        if "BUILD_START:" in chunk:
            self.current_phase = "build"
            self.phase_started = time.time()
            self.build_frac = 0.02
            self.build_label = "basliyor"
        m = re.search(r"BUILD_PROGRESS: (\w+) step (\d+)/(\d+) %(\d+)", chunk)
        if m:
            self.current_phase = "build"
            cur, tot, pct = int(m.group(2)), int(m.group(3)), int(m.group(4))
            self.build_frac = max(self.build_frac, pct / 100.0)
            self.build_label = f"adim {cur}/{tot}"
        if "BUILD_PROGRESS:" in chunk and "npm" in chunk:
            self.build_frac = max(self.build_frac, 0.55)
            self.build_label = "npm install/build"
        if "BUILD_PROGRESS:" in chunk and "next" in chunk:
            self.build_frac = max(self.build_frac, 0.72)
            self.build_label = "next.js build"
        if "BUILD_PROGRESS:" in chunk and "export" in chunk:
            self.build_frac = max(self.build_frac, 0.90)
            self.build_label = "image export"
        if "BUILD_DONE:" in chunk:
            self.build_frac = 1.0
            self.build_label = "tamam"
            self.phase_done.add("build")
        if "↻" in chunk or "cp+restart" in chunk:
            self.current_phase = "live"
            self.phase_started = time.time()
        if "SMART_DEPLOY_DONE" in chunk or "SMART_DEPLOY_PARTIAL" in chunk:
            self.mark_done("finish", "done")
            self._floor_pct = 100

    def _phase_progress_sec(self) -> float:
        completed = 0.0
        order = ["prep", "fleet", "heal", "idle", "build", "finish"]
        live_keys = [k for k in self._budgets if k.startswith("live:")]

        for key in order:
            budget = self._budgets.get(key, 0)
            if not budget:
                continue
            if key in self.phase_done:
                completed += budget
            elif key == self.current_phase:
                if key == "build":
                    completed += budget * max(0.05, self.build_frac)
                else:
                    elapsed = time.time() - self.phase_started
                    completed += min(budget * 0.88, elapsed)

        for key in live_keys:
            budget = self._budgets[key]
            if key in self.phase_done:
                completed += budget
            elif self.current_phase in ("live", "work"):
                elapsed = time.time() - self.phase_started
                live_n = max(1, len(live_keys))
                completed += min(budget * 0.85, elapsed / live_n)

        if self.current_phase == "work" and "build" not in self._budgets and not live_keys:
            idle = self._budgets.get("idle", 0)
            if idle:
                elapsed = time.time() - self.phase_started
                completed += min(idle * 0.9, elapsed)

        return completed

    def progress_pct(self) -> int:
        total = self.total_budget
        if total <= 0:
            return 1
        pct = int(self._phase_progress_sec() / total * 100)
        pct = max(self._floor_pct, min(99, pct))
        self._floor_pct = pct
        return pct

    def remaining_sec(self) -> int:
        total = self.total_budget
        done = self._phase_progress_sec()
        return max(MIN_REMAINING_S, int(total - done))

    def phase_display(self) -> str:
        labels = {
            "prep": "git+SSH",
            "fleet": "VPS tarama",
            "fleet_scan": "VPS tarama",
            "work": "deploy",
            "build": f"dashboard build {self.build_label}".strip(),
            "live": "servis restart",
            "finish": "bitiyor",
            "done": "bitti",
        }
        return labels.get(self.current_phase, self.current_phase)

    def _tick(self) -> None:
        while not self._stop.wait(1.0):
            elapsed = time.time() - self.start
            pct = self.progress_pct()
            remaining = self.remaining_sec()
            phase = self.phase_display()
            line = (
                f"\r  ⏱ {fmt_duration(elapsed)} | kalan ~{fmt_duration(remaining)} "
                f"| %{pct} | {phase}   "
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
        sys.stdout.write("\r" + " " * 90 + "\r")
        sys.stdout.flush()
        return elapsed

    @property
    def total_est(self) -> int:
        return self.total_budget


def commit_files_plan() -> tuple[list[str], dict]:
    _, out = run_local(["git", "show", "--name-only", "--pretty=format:", "HEAD"])
    files = [ln.strip() for ln in out.splitlines() if ln.strip()]
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        from smart_deploy_remote import filter_deploy_only_files, resolve_services  # noqa: WPS433

        filtered = filter_deploy_only_files(files)
        return filtered, resolve_services(filtered)
    except Exception:
        return files, {}


# Eski isim uyumlulugu
DeployTimer = DeployProgressTimer


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


def git_head_short(length: int = 12) -> str:
    _, out = run_local(["git", "rev-parse", f"--short={length}", "HEAD"])
    return out.splitlines()[-1].strip().lower() if out else ""


def shas_match(a: str, b: str) -> bool:
    """Kisa/uzun SHA ayni commit mi (prefix eslesmesi)."""
    x, y = a.strip().lower(), b.strip().lower()
    if not x or not y:
        return False
    if x == y:
        return True
    short, long = (x, y) if len(x) <= len(y) else (y, x)
    return long.startswith(short)


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
    print(f"  On tahmin: ~{fmt_duration(est_sec)} ({est_detail})")
    if pending_files:
        print(f"  Degisen dosya (commit oncesi): {len(pending_files)}")
    if history.get("totals"):
        avg = int(sum(history["totals"][-5:]) / len(history["totals"][-5:]))
        print(f"  Son deploy ort.: ~{fmt_duration(avg)}")
    print()

    total_timer = DeployProgressTimer(local_plan, history)
    total_timer.start_tick()
    deploy_plan: dict | None = None

    print("[1/4] Git push...")
    t0 = time.time()
    ok, git_out = git_push(version, short_sha)
    if not ok:
        total_timer.stop()
        print(f"  HATA git: {git_out[:300]}")
        return 1
    expected_sha = git_head_short(12) or short_sha
    commit_files, commit_affected = commit_files_plan()
    commit_plan = plan_from_local(commit_affected, history)
    if commit_plan.get("update_build") or commit_plan.get("update_live"):
        total_timer.set_plan(commit_plan, "commit dosyalari")
        est_sec, est_detail = estimate_total_seconds(commit_plan, history)
        print(f"  OK — {expected_sha} | plan: ~{fmt_duration(est_sec)} ({est_detail})")
    else:
        print(f"  OK — commit {expected_sha} ({fmt_duration(time.time() - t0)})")

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

    print("\n[3/4] VPS git sync...")
    t0 = time.time()
    sync_cmd = (
        f"cd {prom_dir} && "
        f"git fetch origin master 2>&1 && "
        f"git reset --hard origin/master 2>&1 && "
        f"git rev-parse --short HEAD"
    )
    _, o, e = c.exec_command(sync_cmd, timeout=180)
    sync_out = (o.read() + e.read()).decode("utf-8", errors="replace").strip()
    lines = [ln.strip() for ln in sync_out.splitlines() if ln.strip()]
    vps_sha = lines[-1] if lines else ""
    print(sync_out[-600:] if len(sync_out) > 600 else sync_out)

    if not vps_sha or not all(c in "0123456789abcdef" for c in vps_sha.lower()):
        total_timer.stop()
        print("  HATA: VPS git sync basarisiz")
        return 1

    if not shas_match(vps_sha, expected_sha):
        total_timer.stop()
        print(f"  HATA: VPS SHA ({vps_sha}) != PC ({expected_sha}) — kod yansimadi")
        print("  Cozum: VPS'te manuel: cd /root/prometheus && git fetch && git reset --hard origin/master")
        return 1
    print(f"  OK — VPS {vps_sha} = PC {expected_sha} ({fmt_duration(time.time() - t0)})")
    total_timer.mark_done("prep", "fleet")

    pc_esc = json.dumps(commit_files or pending_files, ensure_ascii=False).replace("'", "'\\''")
    vps_est = total_timer.total_budget - (PHASE_GIT_S + PHASE_SSH_S + PHASE_PULL_S)
    print(f"\n[4/4] Akilli deploy (tahmini ~{fmt_duration(max(60, vps_est))})...")
    print("-" * 68)

    transport = c.get_transport()
    channel = transport.open_session() if transport else None
    if not channel:
        total_timer.stop()
        print("HATA: SSH channel")
        return 1
    channel.settimeout(7200)
    channel.exec_command(
        f"cd {prom_dir} && "
        f"DEPLOY_EXPECTED_SHA={expected_sha} "
        f"DEPLOY_PC_FILES='{pc_esc}' "
        f"python3 -u scripts/smart_deploy_remote.py"
    )
    buf: list[str] = []
    deadline = time.time() + 7200
    while True:
        if channel.recv_ready():
            chunk = channel.recv(8192).decode("utf-8", errors="replace")
            if chunk:
                buf.append(chunk)
                total_timer.on_output(chunk)
                if "DEPLOY_PLAN:" in chunk and not deploy_plan:
                    deploy_plan = parse_deploy_plan(chunk)
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
            print("\nHATA: Zaman asimi (120dk)")
            c.close()
            return 1
        time.sleep(0.05)

    out = "".join(buf)
    code = channel.recv_exit_status()
    c.close()

    total_elapsed = total_timer.stop()
    final_plan = deploy_plan or commit_plan or local_plan
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
        applied = (deploy_plan or {}).get("update_live", []) + (deploy_plan or {}).get("update_build", [])
        if pending_files and not applied:
            print("  UYARI: PC'de dosya vardi ama VPS'te hic servis guncellenmedi!")
            print("  Dashboard ana sayfasinda 'Deploy durumu' paneline bakin.")
        print(f"  BASARILI — Dashboard: v{version}")
        print("  Son deploy saati: ana sayfa + ust menu")
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
