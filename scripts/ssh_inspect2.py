#!/usr/bin/env python3
import os
import paramiko

P = os.environ.get("SSH_PASSWORD", "")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("194.163.181.39", username="root", password=P, timeout=30, allow_agent=False, look_for_keys=False)

cmds = [
    "grep '^GROQ_API_KEY_1=' /root/prometheus/.env | wc -c",
    "cd /root/prometheus && docker compose config 2>&1 | grep -E 'GROQ_API_KEY_1|CEREBRAS_API_KEY_1' | head -6",
    "docker inspect prometheus_agents --format '{{json .Config.Env}}' | tr ',' '\\n' | grep -i GROQ | head -15",
    "docker inspect prometheus_dashboard --format '{{json .Config.Env}}' | tr ',' '\\n' | grep -i GROQ | head -10",
    "cd /root/prometheus && docker compose exec -T agent_system printenv GROQ_API_KEY_1 2>&1 | head -1",
]
for cmd in cmds:
    print("===", cmd[:70])
    _, o, e = c.exec_command(cmd, timeout=60)
    print(o.read().decode())
    er = e.read().decode()
    if er:
        print("err:", er)
c.close()
