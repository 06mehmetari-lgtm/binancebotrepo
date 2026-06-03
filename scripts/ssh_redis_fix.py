#!/usr/bin/env python3
import os
import paramiko

P = os.environ["SSH_PASSWORD"]
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("194.163.181.39", username="root", password=P, timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd):
    print(">>>", cmd[:80])
    _, o, e = c.exec_command(cmd, timeout=60)
    out = o.read().decode()
    err = e.read().decode()
    print(out[:1500])
    if err.strip():
        print("err:", err[:500])
    return out

run("grep '^REDIS_PASSWORD=' /root/prometheus/.env | sed 's/=.*/=***/'")
# try auth with .env password
run(
    'RP=$(grep "^REDIS_PASSWORD=" /root/prometheus/.env | cut -d= -f2- | tr -d "\\r"); '
    'docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning PING 2>&1'
)
run("docker compose -f /root/prometheus/docker-compose.yml logs dashboard --tail 15 2>&1 | tail -15")
# recreate dashboard only with current env
run(
    "cd /root/prometheus && export REDIS_PASSWORD=$(grep '^REDIS_PASSWORD=' .env|cut -d= -f2-) && "
    "docker compose up -d --force-recreate dashboard"
)
run("sleep 8")
run("curl -s -m 20 http://127.0.0.1:3000/api/learning 2>&1 | head -c 400")
c.close()
