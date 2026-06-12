#!/usr/bin/env python3
"""
Prometheus tam VPS deploy — PROMETHEUS_AYAGA_KALDIR.bat tarafından çalıştırılır.

Gizli bilgiler: scripts/.deploy.secrets (gitignore)
Örnek: scripts/.deploy.secrets.example

Kullanım:
  set VPS_PASS=...
  set OPENROUTER_API_KEY=...
  python scripts/prometheus_full_deploy.py

  python scripts/prometheus_full_deploy.py --mode quick
  python scripts/prometheus_full_deploy.py --no-cache
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SECRETS_FILE = Path(__file__).resolve().parent / ".deploy.secrets"
BOOTSTRAP_LOCAL = Path(__file__).resolve().parent / "prometheus_remote_bootstrap.sh"
BOOTSTRAP_REMOTE = "/tmp/prometheus_remote_bootstrap.sh"

DEFAULT_HOST = "194.163.181.39"
DEFAULT_USER = "root"
DEFAULT_DIR = "/root/prometheus"
DEFAULT_REPO = "https://github.com/06mehmetari-lgtm/binancebotrepo.git"
CONNECT_TIMEOUT = 45
TIMEOUT_BY_MODE = {"skip": 900, "quick": 3600, "full": 7200}
DEFAULT_DEPLOY_MODE = "quick"


def load_secrets() -> dict[str, str]:
    data: dict[str, str] = {}
    if SECRETS_FILE.exists():
        for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    for key in (
        "VPS_HOST",
        "VPS_USER",
        "VPS_PASS",
        "OPENROUTER_API_KEY",
        "VPS_PROJECT_DIR",
        "DEPLOY_MODE",
        "BUILD_NO_CACHE",
    ):
        if os.environ.get(key):
            data[key] = os.environ[key]
    return data


def require_paramiko():
    try:
        import paramiko  # noqa: F401
    except ImportError:
        print("paramiko yüklü değil — kuruluyor...")
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
        print("paramiko kuruldu.")


def stream_command(client, cmd: str, timeout: int) -> tuple[int, str]:
    import paramiko

    safe = cmd
    for secret in (os.environ.get("VPS_PASS", ""), os.environ.get("OPENROUTER_API_KEY", "")):
        if secret and len(secret) > 8:
            safe = safe.replace(secret, "***")
    print(f"\n>>> {safe[:200]}{'...' if len(safe) > 200 else ''}")

    _stdin, stdout, _stderr = client.exec_command(cmd, timeout=timeout, get_pty=True)
    channel = stdout.channel
    channel.settimeout(3)
    chunks: list[bytes] = []
    deadline = time.time() + timeout
    last_print = time.time()

    last_data = time.time()
    while not channel.exit_status_ready():
        if time.time() > deadline:
            raise TimeoutError(f"Komut zaman aşımı ({timeout}s)")
        if channel.recv_ready():
            chunk = channel.recv(16384)
            chunks.append(chunk)
            text = chunk.decode("utf-8", errors="replace")
            if text:
                print(text, end="", flush=True)
                last_data = time.time()
        else:
            # Uzun build adiminda heartbeat (takilmadi mesaji)
            if time.time() - last_data > 180:
                elapsed = int(time.time() - (deadline - timeout))
                print(
                    f"\n... hala calisiyor ({elapsed}s) — Docker build uzun surebilir, bekleyin ...\n",
                    flush=True,
                )
                last_data = time.time()
            time.sleep(0.3)

    while channel.recv_ready():
        chunks.append(channel.recv(16384))

    out = b"".join(chunks).decode("utf-8", errors="replace")
    code = channel.recv_exit_status()
    if out.strip():
        print(out[-12000:] if len(out) > 12000 else out)
    print(f"\n[exit {code}]")
    return code, out


def upload_bootstrap(client) -> None:
    if not BOOTSTRAP_LOCAL.exists():
        raise FileNotFoundError(f"Bootstrap script yok: {BOOTSTRAP_LOCAL}")
    content = BOOTSTRAP_LOCAL.read_text(encoding="utf-8").replace("\r\n", "\n")
    sftp = client.open_sftp()
    with sftp.file(BOOTSTRAP_REMOTE, "w") as f:
        f.write(content)
    sftp.close()
    stream_command(client, f"chmod +x {BOOTSTRAP_REMOTE}", 30)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prometheus VPS tam deploy")
    parser.add_argument("--mode", choices=("full", "quick", "skip"), default=None)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--host", default=None)
    parser.add_argument("--dir", default=None)
    args = parser.parse_args()

    secrets = load_secrets()
    host = args.host or secrets.get("VPS_HOST", DEFAULT_HOST)
    user = secrets.get("VPS_USER", DEFAULT_USER)
    password = secrets.get("VPS_PASS", "")
    or_key = secrets.get("OPENROUTER_API_KEY", "")
    prom_dir = args.dir or secrets.get("VPS_PROJECT_DIR", DEFAULT_DIR)
    mode = args.mode or secrets.get("DEPLOY_MODE", DEFAULT_DEPLOY_MODE)
    if mode not in TIMEOUT_BY_MODE:
        mode = DEFAULT_DEPLOY_MODE
    bootstrap_timeout = TIMEOUT_BY_MODE[mode]
    no_cache = "1" if args.no_cache or secrets.get("BUILD_NO_CACHE") == "1" else "0"

    if not password:
        print("=" * 60)
        print(" HATA: VPS şifresi gerekli")
        print("=" * 60)
        print()
        print(" 1) scripts/.deploy.secrets dosyası oluşturun:")
        print(f"    copy scripts\\.deploy.secrets.example scripts\\.deploy.secrets")
        print()
        print(" 2) Veya ortam değişkeni:")
        print("    set VPS_PASS=sifreniz")
        print("    set OPENROUTER_API_KEY=sk-or-v1-...")
        print()
        return 1

    if not or_key:
        print("UYARI: OPENROUTER_API_KEY yok — LLM OpenRouter çalışmayabilir (Ollama fallback)")

    require_paramiko()
    import paramiko

    print("=" * 60)
    print(" PROMETHEUS — TAM VPS DEPLOY")
    print(f" Sunucu : {user}@{host}")
    print(f" Dizin  : {prom_dir}")
    print(f" Mod    : {mode} (skip=~3dk | quick=~10dk | full=~25dk paralel)")
    print(f" Timeout: {bootstrap_timeout}s")
    print("=" * 60)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    for attempt in range(1, 6):
        try:
            print(f"\nSSH bağlanıyor (deneme {attempt}/5)...")
            client.connect(
                host,
                username=user,
                password=password,
                timeout=CONNECT_TIMEOUT,
                banner_timeout=CONNECT_TIMEOUT,
                auth_timeout=CONNECT_TIMEOUT,
            )
            break
        except Exception as exc:
            print(f"SSH hata: {exc}")
            if attempt >= 5:
                return 1
            time.sleep(10)
    else:
        return 1

    print("SSH OK")

    # Proje dizini yoksa otomatik clone
    code, out = stream_command(client, f"test -d {prom_dir} && echo DIR_OK || echo DIR_MISSING", 30)
    if "DIR_MISSING" in out:
        print(f"Sunucuda {prom_dir} yok — otomatik git clone...")
        parent = os.path.dirname(prom_dir.rstrip("/")) or "/root"
        repo = secrets.get("VPS_REPO_URL", DEFAULT_REPO)
        clone_cmd = (
            f"mkdir -p {parent} && "
            f"git clone {repo} {prom_dir} 2>&1 || "
            f"(cd {prom_dir} && git fetch origin && git checkout master)"
        )
        c2, out2 = stream_command(client, clone_cmd, 300)
        _, verify = stream_command(
            client,
            f"test -f {prom_dir}/docker-compose.yml && echo DIR_OK || echo DIR_MISSING",
            30,
        )
        if c2 != 0 or "DIR_OK" not in verify:
            print(f"HATA: Otomatik clone basarisiz — {prom_dir}")
            client.close()
            return 1
        print("OK: Repo clone tamam")

    upload_bootstrap(client)

    # Hassas anahtarları komut satırına yazma — geçici env dosyası
    remote_env = "/tmp/prometheus_deploy.env"
    env_lines = [
        f"PROMETHEUS_DIR={prom_dir}",
        f"DEPLOY_MODE={mode}",
        f"BUILD_NO_CACHE={no_cache}",
    ]
    if or_key:
        env_lines.append(f"OPENROUTER_API_KEY={or_key}")
    sftp = client.open_sftp()
    with sftp.file(remote_env, "w") as f:
        f.write("\n".join(env_lines) + "\n")
    sftp.close()
    stream_command(client, f"chmod 600 {remote_env}", 15)

    cmd = f"set -a && source {remote_env} && set +a && bash {BOOTSTRAP_REMOTE}"
    try:
        code, out = stream_command(client, cmd, bootstrap_timeout)
    except TimeoutError as exc:
        print(f"\nZAMAN AŞIMI: {exc}")
        print("Sunucuda log: /tmp/prometheus_bootstrap.log")
        print("Build log: /tmp/prometheus_build.log")
        client.close()
        return 1

    # Son durum + otomatik iyilestirme
    post_cmd = f"""
cd {prom_dir}
echo '--- container durumu ---'
docker compose ps --format '{{{{.Name}}}} {{{{.Status}}}}' 2>/dev/null | head -25
echo '--- restarting unhealthy ---'
for c in $(docker compose ps --format '{{{{.Name}}}}' 2>/dev/null); do
  st=$(docker inspect --format '{{{{.State.Status}}}}' "$c" 2>/dev/null || echo unknown)
  if [ "$st" = "restarting" ] || [ "$st" = "exited" ]; then
    echo "restart $c ($st)"
    docker restart "$c" 2>/dev/null || true
  fi
done
sleep 5
echo '--- API son kontrol ---'
curl -sf -o /dev/null -w 'dashboard /api/status %{{http_code}}\\n' --max-time 15 http://localhost:3000/api/status || echo 'dashboard bekleniyor'
tail -3 /tmp/prometheus_bootstrap.log 2>/dev/null
"""
    stream_command(client, post_cmd, 120)

    stream_command(client, f"rm -f {remote_env}", 15)
    client.close()

    ok = code == 0 and "BOOTSTRAP_DONE" in out
    print()
    print("=" * 60)
    if ok:
        print(" DEPLOY BAŞARILI")
        print(f" Dashboard: http://{host}:3000")
        print(f" System:    http://{host}:3000/system")
        print(f" Signals:   http://{host}:3000/signals")
        print(f" Positions: http://{host}:3000/positions")
        print()
        print(" İlk 2-3 dakika heartbeat beklenir — sonra sayfalar dolar.")
    else:
        print(" DEPLOY UYARI/HATA — logları kontrol edin")
        print(f" SSH: ssh {user}@{host}")
        print(" Log: tail -100 /tmp/prometheus_bootstrap.log")
    print("=" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
