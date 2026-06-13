#!/usr/bin/env python3
"""Karlilik teşhisi — VPS Redis trade_history analizi."""
from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

import paramiko

SECRETS = Path(__file__).resolve().parent / ".deploy.secrets"


def main() -> None:
    s = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            s[k.strip()] = v.strip()

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(s["VPS_HOST"], username=s["VPS_USER"], password=s["VPS_PASS"], timeout=30, allow_agent=False, look_for_keys=False)
    P = "cd /root/prometheus; RP=$(grep '^REDIS_PASSWORD=' .env|cut -d= -f2-); "

    _, o, _ = c.exec_command(
        P + 'docker exec prometheus_redis redis-cli -a "$RP" --no-auth-warning LRANGE oms:trade_history 0 499',
        timeout=120,
    )
    raw = o.read().decode("utf-8", errors="replace")
    c.close()

    trades: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line == "(nil)":
            continue
        try:
            trades.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    if not trades:
        print("HATA: oms:trade_history bos")
        return

    trades.sort(key=lambda t: float(t.get("closed_at", 0)))

    pnls = [float(t.get("pnl_pct", 0)) for t in trades]
    usd = [float(t.get("pnl_usdt", 0)) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_usd = [u for u in usd if u > 0]
    loss_usd = [u for u in usd if u <= 0]

    wr = len(wins) / len(pnls)
    avg_win = statistics.mean(wins) if wins else 0
    avg_loss = abs(statistics.mean(losses)) if losses else 0
    avg_win_usd = statistics.mean(win_usd) if win_usd else 0
    avg_loss_usd = abs(statistics.mean(loss_usd)) if loss_usd else 0
    gross_win = sum(win_usd)
    gross_loss = abs(sum(loss_usd))
    true_pf = gross_win / gross_loss if gross_loss > 0 else 0
    fake_pf = avg_win_usd / avg_loss_usd if avg_loss_usd > 0 else 0
    breakeven_wr = 1 / (1 + (avg_win / avg_loss)) if avg_loss > 0 and avg_win > 0 else 0

    holds = [float(t.get("hold_seconds", 0)) for t in trades if t.get("hold_seconds")]
    fees = sum(float(t.get("fee_total_usd", 0) or 0) for t in trades)

    reasons = Counter(str(t.get("exit_reason", t.get("close_reason", "?")))[:60] for t in trades)
    symbols_loss = Counter(t.get("symbol") for t in trades if float(t.get("pnl_pct", 0)) <= 0)

    # Son 50 vs ilk 450
    recent = trades[-50:]
    old = trades[:-50] if len(trades) > 50 else []
    def wr_of(ts):
        if not ts:
            return 0
        return sum(1 for t in ts if float(t.get("pnl_pct", 0)) > 0) / len(ts)

    print("=" * 68)
    print("  KARLILIK TESHISI — oms:trade_history")
    print("=" * 68)
    print(f"  Toplam islem:        {len(trades)}")
    print(f"  Win rate:            {wr*100:.1f}%")
    print(f"  Breakeven WR gerek:  {breakeven_wr*100:.1f}%  (mevcut ort kazanc/zarar oranina gore)")
    print(f"  Toplam PnL USDT:     {sum(usd):+.2f}")
    print(f"  Ort kazanc:          {avg_win*100:+.3f}%  (${avg_win_usd:+.2f})")
    print(f"  Ort zarar:           {-avg_loss*100:.3f}%  (${-avg_loss_usd:.2f})")
    print(f"  Gercek profit factor: {true_pf:.2f}  (toplam kazanc / toplam zarar)")
    print(f"  Dashboard PF:        {fake_pf:.2f}  (ort kazanc/ort zarar — YANILTICI)")
    print(f"  Toplam fee (kayitli): ${fees:.2f}")
    print(f"  Ort tutma:           {statistics.mean(holds):.0f} sn" if holds else "")
    print(f"  Son 50 WR:           {wr_of(recent)*100:.1f}%")
    if old:
        print(f"  Eski {len(old)} WR:        {wr_of(old)*100:.1f}%")
    print()
    print("  En sik kapanis nedenleri:")
    for r, n in reasons.most_common(8):
        print(f"    {n:4d}x  {r}")
    print()
    print("  En cok zarar ettiren semboller:")
    for sym, n in symbols_loss.most_common(10):
        print(f"    {sym}: {n} zararli islem")
    print()
    print("  En kotu 10 islem:")
    for t in sorted(trades, key=lambda x: float(x.get("pnl_pct", 0)))[:10]:
        print(
            f"    {t.get('symbol','?'):12s} {float(t.get('pnl_pct',0))*100:+6.2f}%  "
            f"${float(t.get('pnl_usdt',0)):+.2f}  {str(t.get('exit_reason',''))[:40]}"
        )
    print("=" * 68)


if __name__ == "__main__":
    main()
