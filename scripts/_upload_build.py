import os
import sys
import time

import paramiko

PASS = os.environ["VPS_PASS"]
HOST = "194.163.181.39"
SCRIPT = os.path.join(os.path.dirname(__file__), "remote_build.sh")


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", password=PASS, timeout=30)

    sftp = client.open_sftp()
    sftp.put(SCRIPT, "/tmp/remote_build.sh")
    sftp.close()

    client.exec_command("chmod +x /tmp/remote_build.sh", timeout=10)
    client.exec_command("nohup /tmp/remote_build.sh > /tmp/remote_build.out 2>&1 &", timeout=10)

    for i in range(120):
        time.sleep(15)
        _i, stdout, _e = client.exec_command(
            "grep -q BUILD_EXIT: /tmp/prom_build.log 2>/dev/null && tail -5 /tmp/prom_build.log || echo WAIT",
            timeout=30,
        )
        out = stdout.read().decode()
        print(f"poll {i+1}:", out[-500:])
        if "BUILD_EXIT:" in out:
            break
    else:
        print("timeout")
        sys.exit(1)

    _i, stdout, _e = client.exec_command(
        "sleep 8 && curl -s http://localhost:3000/api/llm/health | head -c 1000",
        timeout=60,
    )
    print(stdout.read().decode())
    client.close()
    print("DONE")


if __name__ == "__main__":
    main()
