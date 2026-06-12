#!/usr/bin/env python3
from pathlib import Path
import paramiko

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "scripts" / ".deploy.secrets"


def load_secrets():
    out = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def run_cmd(c, cmd, timeout=120):
    _, o, e = c.exec_command(cmd, timeout=timeout)
    return o.read().decode("utf-8", errors="replace").strip()


def main():
    s = load_secrets()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(s["VPS_HOST"], username=s["VPS_USER"], password=s["VPS_PASS"], timeout=30, allow_agent=False, look_for_keys=False)
    P = "cd /root/prometheus; "

    sections = [
        ("OMS ISLEM GECMISI (6s)", P + r"docker compose logs oms --since 6h 2>/dev/null | grep -iE 'entry|opened|closed|buy|sell|filled|reject|immunity|executed|dca|position' | grep -iv risk_limits | tail -60"),
        ("OMS SON MESAJLAR", P + r"docker compose logs oms --tail 500 2>/dev/null | grep -iv risk_limits | tail -40"),
        ("GUARD 6 SAAT", P + r"docker compose logs agent_system --since 6h 2>/dev/null | grep -iE 'GUARD|entry|opened|close|buy|sell|chart' | tail -50"),
        ("SINYAL YUKSEK CONF", P + r"docker compose logs signal_engine --since 30m 2>/dev/null | grep -iE 'conf=0\.[6-9]|conf=0\.8|conf=0\.9' | tail -45"),
        ("SHADOW ISLEMLER", P + r"docker compose logs shadow_system --since 6h 2>/dev/null | grep -iE 'open|close|fill|trade|entry|pnl|promot' | tail -30"),
    ]
    for title, cmd in sections:
        print(f"\n=== {title} ===\n{run_cmd(c, cmd)}\n")

    rp = (
        P + 'RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-); '
        'echo "TUM POZISYONLAR:"; '
        'docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning KEYS "oms:position:*"; '
        'for k in $(docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning KEYS "oms:position:*" 2>/dev/null); do '
        'echo ">> $k"; docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning GET "$k"; done; '
        'echo "GUARD KARARLARI:"; '
        'for k in $(docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning KEYS "guard:position:*" 2>/dev/null); do '
        'echo ">> $k"; docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning GET "$k" | head -c 350; echo; done; '
        'echo "PORTFOLIO:"; docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning GET portfolio:state | head -c 800; echo; '
        'echo "SCANNER:"; docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning GET scanner:latest | head -c 600'
    )
    print("=== REDIS DETAY ===\n" + run_cmd(c, rp, 180))
    c.close()


if __name__ == "__main__":
    main()
