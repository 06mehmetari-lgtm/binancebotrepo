#!/usr/bin/env python3
"""VPS'te dashboard build — takilan deploy sonrasi tek servis."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "scripts" / ".deploy.secrets"
REBUILD_SH = ROOT / "scripts" / "vps_dashboard_rebuild.sh"


def main() -> int:
    if not SECRETS.exists():
        print("HATA: scripts/.deploy.secrets yok")
        return 1
    if not REBUILD_SH.exists():
        print("HATA: scripts/vps_dashboard_rebuild.sh yok")
        return 1

    cfg: dict[str, str] = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()

    prom_dir = cfg.get("VPS_PROJECT_DIR", "/root/prometheus")
    host = cfg.get("VPS_HOST", "194.163.181.39")
    user = cfg.get("VPS_USER", "root")
    password = cfg.get("VPS_PASS", "")

    print("=" * 60)
    print("  DASHBOARD REBUILD (VPS)")
    print("=" * 60)
    print(f"  Host: {user}@{host}")
    print()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=user, password=password, timeout=30,
                       allow_agent=False, look_for_keys=False)
    except Exception as exc:
        print(f"HATA SSH: {exc}")
        return 1

    sync_cmd = (
        f"cd {prom_dir} && git fetch origin master 2>&1 && "
        f"git reset --hard origin/master 2>&1"
    )
    _, stdout, stderr = client.exec_command(sync_cmd, timeout=180)
    sync_out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace")
    print(sync_out.strip()[-400:] if len(sync_out) > 400 else sync_out.strip())

    remote_sh = f"{prom_dir}/scripts/vps_dashboard_rebuild.sh"
    sh_text = REBUILD_SH.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    sftp = client.open_sftp()
    with sftp.file(remote_sh, "w") as remote:
        remote.write(sh_text)
    sftp.chmod(remote_sh, 0o755)
    sftp.close()

    print("\nBuild basliyor (5-15 dk, dusuk RAM'de yavas olabilir)...")
    print("-" * 60)
    transport = client.get_transport()
    channel = transport.open_session() if transport else None
    if not channel:
        print("HATA: SSH channel")
        return 1
    channel.settimeout(3600)
    channel.get_pty()
    channel.exec_command(f"bash {remote_sh}")
    deadline = time.time() + 3600
    while True:
        if channel.recv_ready():
            chunk = channel.recv(8192).decode("utf-8", errors="replace")
            if chunk:
                sys.stdout.write(chunk)
                sys.stdout.flush()
        if channel.exit_status_ready():
            while channel.recv_ready():
                chunk = channel.recv(8192).decode("utf-8", errors="replace")
                if chunk:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
            break
        if time.time() > deadline:
            print("\nHATA: 60dk zaman asimi")
            client.close()
            return 1
        time.sleep(0.05)

    code = channel.recv_exit_status()
    client.close()
    print("-" * 60)
    if code == 0:
        print(f"\nOK — http://{host}:3000/positions#kasa")
        return 0
    print(f"\nHATA: cikis kodu {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
