#!/usr/bin/env python3
"""Sync .env + pull + recreate LLM services on server."""
import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("SSH_HOST", "194.163.181.39")
USER = os.environ.get("SSH_USER", "root")
PASSWORD = os.environ.get("SSH_PASSWORD", "")
REPO = Path(__file__).resolve().parents[1]
LOCAL_ENV = REPO / ".env"
REMOTE_DIR = "/root/prometheus"


def run_cmd(c, cmd, timeout=300):
    print(f"\n>>> {cmd[:100]}...")
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    if out:
        print(out[-4000:] if len(out) > 4000 else out)
    if err.strip():
        print("stderr:", err[-2000:])
    print(f"exit={code}")
    return code


def main():
    if not PASSWORD:
        sys.exit("SSH_PASSWORD required")
    if not LOCAL_ENV.is_file():
        sys.exit(f"Missing {LOCAL_ENV}")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=30, allow_agent=False, look_for_keys=False)

    run_cmd(c, f"cp {REMOTE_DIR}/.env {REMOTE_DIR}/.env.bak.$(date +%s) 2>/dev/null || true")
    run_cmd(c, f"cd {REMOTE_DIR} && git fetch origin && git reset --hard origin/master")
    # .env git'te izleniyordu — reset sonrası tekrar yükle (kritik sıra)
    sftp = c.open_sftp()
    sftp.put(str(LOCAL_ENV), f"{REMOTE_DIR}/.env")
    sftp.close()
    run_cmd(c, f"sed -i 's/\\r$//' {REMOTE_DIR}/.env && echo stripped_crlf")
    print("Re-uploaded .env after git pull (CRLF stripped)")
    n = run_cmd(c, f"grep -cE '^GROQ_API_KEY' {REMOTE_DIR}/.env || echo 0")
    run_cmd(
        c,
        f"cd {REMOTE_DIR} && export REDIS_PASSWORD=$(grep '^REDIS_PASSWORD=' .env|cut -d= -f2-) && "
        "docker compose up -d --force-recreate agent_system learning_engine dashboard",
        timeout=180,
    )
    run_cmd(c, "sleep 20")
    run_cmd(
        c,
        "docker exec prometheus_agents printenv GROQ_API_KEY_1 2>/dev/null | cut -c1-14 || echo EMPTY",
    )
    run_cmd(
        c,
        f"cd {REMOTE_DIR} && RP=$(grep '^REDIS_PASSWORD=' .env|cut -d= -f2-) && "
        'docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning GET system:llm:status | head -c 300',
    )
    c.close()
    print("\nDone. Rotate root password — it was shared in chat.")


if __name__ == "__main__":
    main()
