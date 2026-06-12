"""One-off VPS deploy — credentials via env VPS_PASS and OPENROUTER_API_KEY."""
import json
import os
import sys
import time

import paramiko

HOST = os.environ.get("VPS_HOST", "194.163.181.39")
USER = os.environ.get("VPS_USER", "root")
PASS = os.environ["VPS_PASS"]
OR_KEY = os.environ["OPENROUTER_API_KEY"]


def run(client, cmd, timeout=600):
    safe = cmd.replace(OR_KEY, "sk-or-***")
    print(">>>", safe[:160])
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=True)
    channel = stdout.channel
    channel.settimeout(timeout)
    chunks = []
    deadline = time.time() + timeout
    while not channel.exit_status_ready():
        if time.time() > deadline:
            raise TimeoutError(f"Command timed out after {timeout}s")
        if channel.recv_ready():
            chunks.append(channel.recv(4096))
        else:
            time.sleep(0.5)
    while channel.recv_ready():
        chunks.append(channel.recv(4096))
    out = b"".join(chunks).decode("utf-8", errors="replace")
    code = channel.recv_exit_status()
    if out.strip():
        print(out[-6000:] if len(out) > 6000 else out)
    print(f"[exit {code}]")
    return code, out


def upload_and_run(client, remote_path: str, content: str, timeout=120):
    sftp = client.open_sftp()
    with sftp.file(remote_path, "w") as f:
        f.write(content)
    sftp.close()
    return run(client, f"python3 {remote_path}", timeout)


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=30)
    print("Connected")

    run(client, "cd ~/prometheus && git pull origin master", 120)

    env_script = f"""import re
from pathlib import Path
p = Path('/root/prometheus/.env')
text = p.read_text() if p.exists() else ''

def set_kv(k, v):
    global text
    pat = re.compile(r'^' + re.escape(k) + r'=.*$', re.M)
    line = k + '=' + v
    if pat.search(text):
        text = pat.sub(line, text)
    else:
        text = (text.rstrip() + '\\n' + line + '\\n') if text else (line + '\\n')

set_kv('OPENROUTER_API_KEY', {json.dumps(OR_KEY)})
set_kv('LLM_PROVIDER_ORDER', 'openrouter,ollama,google,groq,cerebras')
set_kv('PORTFOLIO_TRY', '10000')
set_kv('TRADE_FEE_PCT_PER_SIDE', '0.001')
p.write_text(text)
print('env updated')
"""
    upload_and_run(client, "/tmp/prom_env.py", env_script)

    redis_script = f"""import json, subprocess
from pathlib import Path
text = Path('/root/prometheus/.env').read_text()
rp = None
for line in text.splitlines():
    if line.startswith('REDIS_PASSWORD='):
        rp = line.split('=',1)[1].strip().strip('"').strip("'")
        break
if not rp:
    raise SystemExit('no REDIS_PASSWORD')
key = {json.dumps(OR_KEY)}
cmd = ['docker','compose','exec','-T','redis','redis-cli','-a',rp,'--no-auth-warning','GET','system:llm:key_overrides']
r = subprocess.run(cmd, cwd='/root/prometheus', capture_output=True, text=True)
raw = (r.stdout or '').strip()
try:
    data = json.loads(raw) if raw and raw != '(nil)' else {{}}
except Exception:
    data = {{}}
if not isinstance(data, dict):
    data = {{}}
data['openrouter'] = [key]
payload = json.dumps(data)
subprocess.run(['docker','compose','exec','-T','redis','redis-cli','-a',rp,'--no-auth-warning','SET','system:llm:key_overrides',payload], cwd='/root/prometheus', check=True)
subprocess.run(['docker','compose','exec','-T','redis','redis-cli','-a',rp,'--no-auth-warning','PUBLISH','ch:llm:keys_updated','1'], cwd='/root/prometheus', check=True)
print('redis openrouter key set')
"""
    upload_and_run(client, "/tmp/prom_redis.py", redis_script)

    run(
        client,
        "cd ~/prometheus && nohup docker compose build dashboard oms agent_system learning_engine "
        "> /tmp/prom_build.log 2>&1 & echo $!",
        30,
    )
    for i in range(60):
        time.sleep(30)
        code, out = run(
            client,
            "tail -5 /tmp/prom_build.log 2>/dev/null; "
            "pgrep -f 'docker compose build' >/dev/null && echo BUILD_RUNNING || echo BUILD_DONE",
            60,
        )
        if "BUILD_DONE" in out:
            break
        print(f"build poll {i + 1}/60...")
    run(client, "tail -50 /tmp/prom_build.log", 60)

    run(
        client,
        "cd ~/prometheus && docker compose up -d --force-recreate dashboard oms agent_system learning_engine 2>&1",
        300,
    )
    run(client, "sleep 12 && curl -s http://localhost:3000/api/llm/health | head -c 1200", 60)
    run(
        client,
        "cd ~/prometheus && docker compose exec -T redis sh -c "
        "'redis-cli -a \"$REDIS_PASSWORD\" --no-auth-warning GET portfolio:try:v1' 2>&1 | head -c 600",
        60,
    )
    run(client, "cd ~/prometheus && docker compose logs oms --tail 25 2>&1", 60)
    run(client, "rm -f /tmp/prom_env.py /tmp/prom_redis.py", 30)
    client.close()
    print("DEPLOY DONE")


if __name__ == "__main__":
    main()
