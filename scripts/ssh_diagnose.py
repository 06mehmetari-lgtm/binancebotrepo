#!/usr/bin/env python3
import os
import sys

import paramiko

HOST = os.environ.get("SSH_HOST", "194.163.181.39")
USER = os.environ.get("SSH_USER", "root")
PASSWORD = os.environ.get("SSH_PASSWORD", "")

P = "cd ~/prometheus 2>/dev/null || cd /root/prometheus; "
CMDS = [
    P + "pwd",
    P + "test -f .env && wc -l .env || echo NO_ENV",
    P + "grep -cE '^GROQ_API_KEY' .env 2>/dev/null || echo 0",
    P + "grep '^GROQ_API_KEY_1=' .env | sed 's/=.*/=MASKED/' || echo NO_GROQ1",
    "docker ps --format '{{.Names}} {{.Status}}' | grep prometheus || true",
    "docker exec prometheus_agents printenv GROQ_API_KEY_1 2>/dev/null | cut -c1-14 || echo AGENTS_EMPTY",
    "docker exec prometheus_dashboard printenv GROQ_API_KEY_1 2>/dev/null | cut -c1-14 || echo DASH_EMPTY",
    P + "git log -1 --oneline 2>/dev/null || echo NO_GIT",
    P + "docker compose logs agent_system --tail 25 2>/dev/null | tail -25",
]


def run():
    if not PASSWORD:
        print("Set SSH_PASSWORD", file=sys.stderr)
        sys.exit(1)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=30, allow_agent=False, look_for_keys=False)
    for cmd in CMDS:
        print(f"\n=== {cmd[:70]} ===")
        _, stdout, stderr = c.exec_command(cmd, timeout=60)
        print(stdout.read().decode(errors="replace"))
        err = stderr.read().decode(errors="replace")
        if err.strip():
            print("err:", err)
    # redis
    print("\n=== redis llm status ===")
    _, stdout, _ = c.exec_command(
        P + 'RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-); '
        'docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning GET system:llm:status | head -c 350',
        timeout=30,
    )
    print(stdout.read().decode(errors="replace") or "(nil)")
    c.close()


if __name__ == "__main__":
    run()
