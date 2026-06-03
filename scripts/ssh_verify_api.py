#!/usr/bin/env python3
import os
import paramiko

P = os.environ["SSH_PASSWORD"]
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("194.163.181.39", username="root", password=P, timeout=30, allow_agent=False, look_for_keys=False)
cmds = [
    "docker exec prometheus_redis printenv REDIS_PASSWORD 2>/dev/null | wc -c",
    "grep '^REDIS_PASSWORD=' /root/prometheus/.env | wc -c",
    "docker exec prometheus_agents printenv REDIS_URL 2>/dev/null | sed 's/:[^:@]*@/:***@/'",
    "curl -s -m 15 http://127.0.0.1:3000/api/learning -o /tmp/l.json -w '%{http_code}' && echo && python3 -c \"import json;d=json.load(open('/tmp/l.json'));l=d['llm'];print('source',l.get('status_source'));print('groq',l['groq']);print('groq_ok',any(p['configured'] for p in l['providers'] if p['id']=='groq'))\" 2>&1",
]
for cmd in cmds:
    print("===", cmd[:60])
    _, o, e = c.exec_command(cmd, timeout=45)
    print(o.read().decode())
    if e.read().decode().strip():
        print("err:", e.read().decode()[:200])
c.close()
