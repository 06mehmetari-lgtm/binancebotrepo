#!/usr/bin/env python3
import os
import paramiko

P = os.environ["SSH_PASSWORD"]
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("194.163.181.39", username="root", password=P, timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd, t=90):
    print(">>>", cmd)
    _, o, e = c.exec_command(cmd, timeout=t)
    out = o.read().decode()
    if out:
        print(out[:2000])
    err = e.read().decode()
    if err.strip():
        print("stderr:", err[:400])

run("sed -i 's/\\r$//' /root/prometheus/.env && echo crlf_stripped")
run("cd /root/prometheus && git pull -q && git reset --hard origin/master")
run(
    "cd /root/prometheus && export REDIS_PASSWORD=$(grep '^REDIS_PASSWORD=' .env|cut -d= -f2-) && "
    "docker compose build dashboard",
    t=400,
)
run(
    "cd /root/prometheus && export REDIS_PASSWORD=$(grep '^REDIS_PASSWORD=' .env|cut -d= -f2-) && "
    "docker compose up -d --force-recreate dashboard agent_system learning_engine",
    t=120,
)
run("sleep 12")
run("curl -s -m 25 http://127.0.0.1:3000/api/learning -o /tmp/l.json -w ' http:%{http_code}\\n'")
run("python3 -c \"import json;d=json.load(open('/tmp/l.json'));l=d['llm'];print('source',l.get('status_source'));print('groq',l['groq'])\"")

c.close()
