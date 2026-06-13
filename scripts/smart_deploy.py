#!/usr/bin/env python3
"""
Tek deploy — git push + akilli servis guncelleme + dashboard versiyon.

Kullanim: DEPLOY.bat
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"
VERSION_FILE = REPO / "deploy" / "VERSION.json"
REMOTE_SCRIPT = Path(__file__).resolve().parent / "smart_deploy_remote.py"


def run_local(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd or REPO)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


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

    # Versiyon uret
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

    print("[1/4] Git push...")
    ok, git_out = git_push(version, short_sha)
    if not ok:
        print(f"  HATA git: {git_out[:300]}")
        return 1
    print(f"  OK — {short_sha}")

    print("\n[2/4] VPS baglanti...")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(s["VPS_HOST"], username=s.get("VPS_USER", "root"), password=s["VPS_PASS"],
                  timeout=30, allow_agent=False, look_for_keys=False)
    except Exception as exc:
        print(f"  HATA SSH: {exc}")
        return 1
    print("  OK")

    print("\n[3/4] VPS git pull + script...")
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

    print("\n[4/4] Akilli deploy (sadece degisen servisler)...")
    print("-" * 68)

    transport = c.get_transport()
    channel = transport.open_session() if transport else None
    if not channel:
        print("HATA: SSH channel")
        return 1
    channel.settimeout(2400)
    channel.exec_command(
        f"cd {prom_dir} && python3 -u scripts/smart_deploy_remote.py"
    )
    buf: list[str] = []
    deadline = time.time() + 2400
    while True:
        if channel.recv_ready():
            chunk = channel.recv(8192).decode("utf-8", errors="replace")
            if chunk:
                sys.stdout.write(chunk)
                sys.stdout.flush()
                buf.append(chunk)
        if channel.exit_status_ready():
            while channel.recv_ready():
                chunk = channel.recv(8192).decode("utf-8", errors="replace")
                if chunk:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                    buf.append(chunk)
            break
        if time.time() > deadline:
            print("\nHATA: Zaman asimi")
            c.close()
            return 1
        time.sleep(0.05)

    out = "".join(buf)
    code = channel.recv_exit_status()
    c.close()

    print("\n" + "=" * 68)
    if "SMART_DEPLOY_DONE" in out:
        print(f"  BASARILI — Dashboard ustunde: v{version}")
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
