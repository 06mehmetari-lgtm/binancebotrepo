import os
import sys
import time

import paramiko

PASS = os.environ["VPS_PASS"]
HOST = "194.163.181.39"


def run(client, cmd, timeout=600):
    print(">>>", cmd[:120])
    _i, stdout, _e = client.exec_command(cmd, timeout=timeout, get_pty=True)
    ch = stdout.channel
    deadline = time.time() + timeout
    buf = b""
    while not ch.exit_status_ready():
        if time.time() > deadline:
            raise TimeoutError("timeout")
        if ch.recv_ready():
            buf += ch.recv(8192)
        else:
            time.sleep(1)
    while ch.recv_ready():
        buf += ch.recv(8192)
    out = buf.decode("utf-8", errors="replace")
    code = ch.recv_exit_status()
    if out.strip():
        print(out[-6000:])
    print("[exit", code, "]")
    return code, out


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", password=PASS, timeout=30)

    run(
        client,
        "bash -lc 'cd ~/prometheus && nohup docker compose build dashboard oms agent_system learning_engine signal_engine "
        "> /tmp/prom_build.log 2>&1; echo BUILD_EXIT:$? >> /tmp/prom_build.log' &",
        30,
    )

    for i in range(90):
        time.sleep(20)
        _, out = run(
            client,
            "bash -lc 'test -f /tmp/prom_build.log && tail -2 /tmp/prom_build.log; "
            "grep -q BUILD_EXIT: /tmp/prom_build.log && echo DONE || echo RUNNING'",
            45,
        )
        if "DONE" in out:
            break
        print("poll", i + 1)
    else:
        sys.exit("build timeout")

    run(
        client,
        "cd ~/prometheus && docker compose up -d --force-recreate dashboard oms agent_system learning_engine signal_engine",
        300,
    )
    run(client, "sleep 12 && curl -s http://localhost:3000/api/llm/health | head -c 1200", 60)
    run(client, "cd ~/prometheus && docker compose ps --format '{{.Name}} {{.Status}}' | head -20", 60)
    client.close()
    print("FINISH OK")


if __name__ == "__main__":
    main()
