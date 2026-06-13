#!/usr/bin/env python3
"""Derin karlilik teshisi — VPS'e script yukler, canli cikti akar."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "scripts" / ".deploy.secrets"
REMOTE = ROOT / "scripts" / "profit_deep_diagnosis_remote.py"
REMOTE_PATH = "/root/prometheus/scripts/profit_deep_diagnosis_remote.py"


def _stream_exec(client: paramiko.SSHClient, cmd: str, timeout: int = 600) -> tuple[int, str]:
    """Stdout'u satir satir yaz — kullanici beklerken gorsun."""
    transport = client.get_transport()
    if not transport:
        return 1, "transport yok"
    channel = transport.open_session()
    channel.settimeout(timeout)
    channel.exec_command(cmd)
    buf: list[str] = []
    deadline = time.time() + timeout
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
            return channel.recv_exit_status(), "".join(buf)
        if time.time() > deadline:
            channel.close()
            return 124, "".join(buf) + "\n[HATA] Zaman asimi (600sn)"
        time.sleep(0.05)


def main() -> int:
    if not SECRETS.exists():
        print("HATA: scripts/.deploy.secrets yok — once SSH_SIFRE_DEGISTIR.bat")
        return 1
    if not REMOTE.exists():
        print(f"HATA: {REMOTE} yok")
        return 1

    s: dict[str, str] = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            s[k.strip()] = v.strip()

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(
            s["VPS_HOST"], username=s.get("VPS_USER", "root"), password=s["VPS_PASS"],
            timeout=30, allow_agent=False, look_for_keys=False,
        )
    except paramiko.AuthenticationException:
        print("HATA: SSH sifre yanlis — SSH_SIFRE_DEGISTIR.bat")
        return 1
    except Exception as exc:
        print(f"HATA: SSH: {exc}")
        return 1

    print("Script VPS'e yukleniyor...", flush=True)
    sftp = c.open_sftp()
    try:
        sftp.put(str(REMOTE), REMOTE_PATH)
    except OSError:
        c.exec_command("mkdir -p /root/prometheus/scripts")[1].read()
        sftp.put(str(REMOTE), REMOTE_PATH)
    sftp.close()

    print("Analiz basladi (cikti canli akar, ~30-90 sn)...\n", flush=True)
    code, out = _stream_exec(
        c,
        "cd /root/prometheus && python3 -u scripts/profit_deep_diagnosis_remote.py",
        timeout=600,
    )
    c.close()
    if code == 124:
        print("\nHATA: Zaman asimi — VPS yuku yuksek olabilir (load average kontrol)")
        return 1
    if not out.strip():
        print("HATA: Cikti bos — VPS'te python3 scripts/profit_deep_diagnosis_remote.py deneyin")
        return 1
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
