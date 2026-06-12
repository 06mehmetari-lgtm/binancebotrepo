#!/usr/bin/env python3
"""SHADOW_A trade autopsy — VPS Redis + log analizi."""
from __future__ import annotations

import json
import statistics
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


def pct(x):
    return f"{x * 100:+.3f}%"


def analyze_trades(trades: list[dict]) -> dict:
    if not trades:
        return {"count": 0}
    pnls = [float(t.get("pnl_pct", 0)) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    usd = [float(t.get("pnl_usdt", 0)) for t in trades]
    holds = [float(t.get("hold_seconds", 0)) for t in trades]

    worst = sorted(trades, key=lambda t: float(t.get("pnl_pct", 0)))[:8]
    best = sorted(trades, key=lambda t: float(t.get("pnl_pct", 0)), reverse=True)[:8]

    return {
        "count": len(trades),
        "win_rate": len(wins) / len(pnls),
        "avg_pnl_pct": statistics.mean(pnls),
        "avg_win_pct": statistics.mean(wins) if wins else 0,
        "avg_loss_pct": statistics.mean(losses) if losses else 0,
        "median_win_pct": statistics.median(wins) if wins else 0,
        "median_loss_pct": statistics.median(losses) if losses else 0,
        "sum_pnl_usdt": sum(usd),
        "avg_hold_sec": statistics.mean(holds) if holds else 0,
        "rr_ratio": abs(statistics.mean(wins) / statistics.mean(losses)) if wins and losses and statistics.mean(losses) != 0 else 0,
        "worst": [(t.get("symbol"), float(t.get("pnl_pct", 0)), float(t.get("pnl_usdt", 0))) for t in worst],
        "best": [(t.get("symbol"), float(t.get("pnl_pct", 0)), float(t.get("pnl_usdt", 0))) for t in best],
        "loss_gt_2pct": sum(1 for p in losses if p < -0.02),
        "win_lt_05pct": sum(1 for p in wins if p < 0.005),
    }


def main():
    s = load_secrets()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(s["VPS_HOST"], username=s["VPS_USER"], password=s["VPS_PASS"], timeout=30, allow_agent=False, look_for_keys=False)
    P = "cd /root/prometheus; RP=$(grep '^REDIS_PASSWORD=' .env|cut -d= -f2-); "

    cmds = {
        "leaderboard": P + 'docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning GET shadow:leaderboard',
        "portfolio_a": P + 'docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning GET shadow:portfolio:SHADOW_A',
        "trades_list": P + 'docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning LRANGE shadow:trades:SHADOW_A 0 200',
        "trade_keys": P + 'docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning KEYS "shadow:trade:*" | head -5',
        "pg_trades": P + 'docker exec prometheus_postgres psql -U prometheus -d prometheus_trading -t -A -F"|" -c "SELECT symbol,direction,pnl_pct,pnl_usdt,hold_seconds,is_shadow,opened_at FROM trades WHERE shadow_id=\'SHADOW_A\' OR is_shadow=true ORDER BY opened_at DESC LIMIT 80;" 2>&1',
        "shadow_log_closes": P + r'docker compose logs shadow_system --since 72h 2>/dev/null | grep -iE "CLOSE|OPEN|pnl=" | grep SHADOW_A | tail -80',
    }

    data = {}
    for k, cmd in cmds.items():
        _, o, _ = c.exec_command(cmd, timeout=120)
        data[k] = o.read().decode("utf-8", errors="replace").strip()

    c.close()

    trades: list[dict] = []
    raw_list = data.get("trades_list", "")
    if raw_list and raw_list != "(nil)":
        for line in raw_list.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if not trades:
        port_raw = data.get("portfolio_a", "")
        if port_raw and port_raw != "(nil)":
            try:
                port = json.loads(port_raw)
                trades = port.get("trades") or []
            except json.JSONDecodeError:
                pass

    stats = analyze_trades(trades)

    print("=" * 70)
    print("SHADOW_A AUTOPSY")
    print("=" * 70)
    print("\n--- LEADERBOARD ---")
    print(data.get("leaderboard", "(yok)")[:1200])
    print("\n--- TRADE STATS ---")
    if stats.get("count"):
        print(f"Islem sayisi:     {stats['count']}")
        print(f"Win rate:         {stats['win_rate']*100:.1f}%")
        print(f"Ort PnL/islem:    {pct(stats['avg_pnl_pct'])}")
        print(f"Ort KAZANC:       {pct(stats['avg_win_pct'])}  (medyan {pct(stats['median_win_pct'])})")
        print(f"Ort ZARAR:        {pct(stats['avg_loss_pct'])}  (medyan {pct(stats['median_loss_pct'])})")
        print(f"R:R orani:        {stats['rr_ratio']:.2f}x  (1 kazanc / 1 zarar)")
        print(f"Toplam PnL USDT:  {stats['sum_pnl_usdt']:+.2f}")
        print(f"Ort tutma suresi: {stats['avg_hold_sec']:.0f} sn")
        print(f"Kucuk kazanc <%0.5: {stats['win_lt_05pct']} islem")
        print(f"Buyuk zarar >%2:    {stats['loss_gt_2pct']} islem")
        print("\nEn kotu 8:")
        for sym, p, u in stats["worst"]:
            print(f"  {sym:16} {pct(p)}  ({u:+.2f} USDT)")
        print("\nEn iyi 8:")
        for sym, p, u in stats["best"]:
            print(f"  {sym:16} {pct(p)}  ({u:+.2f} USDT)")
    else:
        print("(Redis'te trade listesi yok — log parse deneniyor)")

    print("\n--- POSTGRES ---")
    print(data.get("pg_trades", "(bos)")[:3000])
    print("\n--- SHADOW LOG (son kapanislar) ---")
    print(data.get("shadow_log_closes", "(bos)")[:4000])

    # Fee impact estimate
    if stats.get("count"):
        fee_per_trade = 0.002  # 0.10% x2
        print(f"\n--- FEE ETKISI ---")
        print(f"Round-trip fee/islem: -{fee_per_trade*100:.2f}%")
        print(f"61 islemde toplam fee drag: ~-{fee_per_trade * stats['count'] * 100:.1f}% birikimli (basit)")


if __name__ == "__main__":
    main()
