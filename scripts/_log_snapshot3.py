#!/usr/bin/env python3
from pathlib import Path
import paramiko

SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"


def load_secrets():
    out = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main():
    s = load_secrets()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(s["VPS_HOST"], username=s["VPS_USER"], password=s["VPS_PASS"], timeout=30, allow_agent=False, look_for_keys=False)
    P = "cd /root/prometheus; "

    cmds = [
        ("OMS 24s ISLEM", P + r"docker compose logs oms --since 24h 2>/dev/null | grep -iE 'open|close|entry|buy|sell|guard|executed|reject|immunity|paper|dca|filled' | grep -iv risk_limits | tail -40"),
        ("GUARD LISTENER", P + r"docker compose logs oms --since 24h 2>/dev/null | grep -i guard | tail -20"),
        ("SHADOW POZ", P + r"docker compose logs shadow_system --since 24h 2>/dev/null | grep -iE 'opened|closed|entry|exit|fill|position' | grep -iv risk_limits | tail -30"),
        ("POSTGRES TRADES", P + r'docker exec prometheus_postgres psql -U prometheus -d prometheus_trading -t -c "SELECT symbol, direction, entry_price, exit_price, pnl_pct, is_shadow, opened_at FROM trades ORDER BY opened_at DESC LIMIT 15;" 2>/dev/null'),
        ("ENV DRY", P + "grep -E '^DRY_RUN=|^BINANCE_TESTNET=|^MAX_OPEN' .env 2>/dev/null"),
        ("SHADOW REDIS", P + 'RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-); docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning KEYS "shadow:position:*" 2>/dev/null | head -20'),
    ]
    for t, cmd in cmds:
        print(f"\n=== {t} ===")
        _, o, _ = c.exec_command(cmd, timeout=120)
        print(o.read().decode("utf-8", errors="replace").strip() or "(bos)")

    rp = (
        P + 'RP=$(grep "^REDIS_PASSWORD=" .env|cut -d= -f2-); '
        'for k in $(docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning KEYS "shadow:position:*" 2>/dev/null); do '
        'echo ">> $k"; docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning GET "$k" | head -c 400; echo; done'
    )
    print("\n=== SHADOW POZ DETAY ===")
    _, o, _ = c.exec_command(rp, timeout=90)
    print(o.read().decode("utf-8", errors="replace").strip() or "(bos)")
    c.close()


if __name__ == "__main__":
    main()
