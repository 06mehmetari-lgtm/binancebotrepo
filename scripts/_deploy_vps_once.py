"""VPS deploy — set VPS_PASS and OPENROUTER_API_KEY env vars before running."""
import json
import os
import sys
import time

import paramiko

HOST = os.environ.get("VPS_HOST", "194.163.181.39")
USER = os.environ.get("VPS_USER", "root")
PASS = os.environ["VPS_PASS"]
OR_KEY = os.environ["OPENROUTER_API_KEY"]
BUILD_TIMEOUT = int(os.environ.get("DEPLOY_BUILD_TIMEOUT", "1200"))


def run(client, cmd, timeout=600):
    safe = cmd.replace(OR_KEY, "sk-or-***")
    print(">>>", safe[:160])
    _stdin, stdout, _stderr = client.exec_command(cmd, timeout=timeout, get_pty=True)
    channel = stdout.channel
    channel.settimeout(5)
    chunks = []
    deadline = time.time() + timeout
    while not channel.exit_status_ready():
        if time.time() > deadline:
            raise TimeoutError(f"timeout {timeout}s")
        if channel.recv_ready():
            chunks.append(channel.recv(8192))
        else:
            time.sleep(1)
    while channel.recv_ready():
        chunks.append(channel.recv(8192))
    out = b"".join(chunks).decode("utf-8", errors="replace")
    code = channel.recv_exit_status()
    if out.strip():
        print(out[-8000:] if len(out) > 8000 else out)
    print(f"[exit {code}]")
    return code, out


def upload(client, path: str, content: str):
    sftp = client.open_sftp()
    with sftp.file(path, "w") as f:
        f.write(content)
    sftp.close()


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=30)
    print("Connected to", HOST)

    run(client, "cd ~/prometheus && git pull origin master", 180)

    upload(
        client,
        "/tmp/prom_env.py",
        f"""import re
from pathlib import Path
p = Path('/root/prometheus/.env')
text = p.read_text() if p.exists() else ''
def set_kv(k, v):
    global text
    pat = re.compile(r'^' + re.escape(k) + r'=.*$', re.M)
    line = k + '=' + v
    text = pat.sub(line, text) if pat.search(text) else (text.rstrip() + '\\n' + line + '\\n')
set_kv('OPENROUTER_API_KEY', {json.dumps(OR_KEY)})
set_kv('LLM_PROVIDER_ORDER', 'openrouter,ollama,google,groq,cerebras')
set_kv('PORTFOLIO_TRY', '10000')
set_kv('TRADE_FEE_PCT_PER_SIDE', '0.001')
p.write_text(text)
print('env ok')
""",
    )
    run(client, "python3 /tmp/prom_env.py", 60)

    upload(
        client,
        "/tmp/prom_redis.py",
        f"""import json, subprocess
from pathlib import Path
rp = next((l.split('=',1)[1].strip().strip('"').strip("'") for l in Path('/root/prometheus/.env').read_text().splitlines() if l.startswith('REDIS_PASSWORD=')), None)
if not rp: raise SystemExit('no redis pass')
key = {json.dumps(OR_KEY)}
r = subprocess.run(['docker','compose','exec','-T','redis','redis-cli','-a',rp,'--no-auth-warning','GET','system:llm:key_overrides'], cwd='/root/prometheus', capture_output=True, text=True)
raw = (r.stdout or '').strip()
data = json.loads(raw) if raw and raw != '(nil)' else {{}}
if not isinstance(data, dict): data = {{}}
data['openrouter'] = [key]
payload = json.dumps(data)
subprocess.run(['docker','compose','exec','-T','redis','redis-cli','-a',rp,'--no-auth-warning','SET','system:llm:key_overrides',payload], cwd='/root/prometheus', check=True)
subprocess.run(['docker','compose','exec','-T','redis','redis-cli','-a',rp,'--no-auth-warning','PUBLISH','ch:llm:keys_updated','1'], cwd='/root/prometheus', check=True)
print('redis ok')
""",
    )
    run(client, "python3 /tmp/prom_redis.py", 120)

    run(
        client,
        "cd ~/prometheus && (docker compose build dashboard oms agent_system learning_engine signal_engine "
        "> /tmp/prom_build.log 2>&1; echo BUILD_EXIT:$? >> /tmp/prom_build.log) &",
        30,
    )

    started = time.time()
    while time.time() - started < BUILD_TIMEOUT:
        time.sleep(20)
        _, out = run(
            client,
            "tail -3 /tmp/prom_build.log 2>/dev/null; grep -q BUILD_EXIT: /tmp/prom_build.log && echo DONE || echo RUNNING",
            45,
        )
        if "DONE" in out:
            break
        print("build running...", int(time.time() - started), "s")
    else:
        print("BUILD TIMEOUT — check /tmp/prom_build.log on server")
        sys.exit(1)

    run(client, "grep BUILD_EXIT: /tmp/prom_build.log | tail -1", 30)
    run(
        client,
        "cd ~/prometheus && docker compose up -d --force-recreate dashboard oms agent_system learning_engine signal_engine",
        300,
    )
    run(client, "sleep 15 && curl -s http://localhost:3000/api/llm/health 2>/dev/null | head -c 1500", 60)
    run(
        client,
        "cd ~/prometheus && docker compose exec -T redis sh -c 'redis-cli -a \"$REDIS_PASSWORD\" --no-auth-warning GET portfolio:try:v1' 2>&1 | head -c 500",
        60,
    )
    run(client, "cd ~/prometheus && docker compose ps --format '{{.Name}} {{.Status}}' | head -25", 60)
    run(client, "rm -f /tmp/prom_env.py /tmp/prom_redis.py", 30)
    client.close()
    print("DEPLOY DONE")


if __name__ == "__main__":
    main()
