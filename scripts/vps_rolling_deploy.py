#!/usr/bin/env python3
"""
Rolling deploy — Faz1: git + canli kod + restart (hemen calisir)
                 Faz2: tum servisler arka planda build (dashboard dahil)

Kullanim: ROLLING_DEPLOY.bat
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"

SCRIPTS = (
    "prometheus_rolling_bootstrap.sh",
    "apply_live_code.sh",
    "background_build_all.sh",
)


def _stream_exec(client, cmd: str, timeout: int = 600) -> tuple[int, str]:
    import paramiko

    transport = client.get_transport()
    if not transport:
        return 1, ""
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
            return 124, "".join(buf)
        time.sleep(0.05)


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

    print("Scriptler VPS'e yukleniyor...", flush=True)
    sftp = c.open_sftp()
    try:
        sftp.mkdir(f"{prom_dir}/scripts")
    except OSError:
        pass
    for name in SCRIPTS:
        local = REPO / "scripts" / name
        sftp.put(str(local), f"{prom_dir}/scripts/{name}")
    sftp.close()

    print("\n" + "=" * 60)
    print("  FAZ 1 — kod cek + canli yukle + restart (~3-5 dk)")
    print("=" * 60 + "\n", flush=True)

    code, out = _stream_exec(
        c,
        f"cd {prom_dir} && chmod +x scripts/*.sh && "
        f"bash scripts/prometheus_rolling_bootstrap.sh",
        timeout=600,
    )

    print("\n" + "=" * 60)
    if "ROLLING_PHASE1_DONE" in out or "FAZ 1 TAMAM" in out:
        print("  FAZ 1 BASARILI — guncel kod simdi calisiyor")
        print(f"  http://{host}:3000/system")
        print()
        print("  FAZ 2 (arka plan): tum servisler + dashboard build ediliyor")
        print("  Durum kontrol:     BG_BUILD_DURUM.bat")
        print("  Log (VPS):         tail -f /tmp/prometheus_bg_build.log")
        ok = True
    elif code == 124:
        print("  ZAMAN ASIMI — sunucuda log kontrol edin")
        ok = False
    else:
        print("  UYARI — faz1 tamamlanmamis olabilir, log kontrol edin")
        ok = code == 0

    if "BG_START" in out or "Arka plan build basladi" in out:
        print("  Arka plan build: BASLATILDI")
    print("=" * 60)

    c.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
