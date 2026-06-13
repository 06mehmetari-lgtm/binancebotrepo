#!/usr/bin/env python3
"""
VPS uzerinde calisir — Redis pipeline + karlilik derin analiz.
Hiz: docker exec prometheus_redis + toplu MGET (tek tek GET yok).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("PROMETHEUS_DIR", "/root/prometheus"))
os.chdir(ROOT)

REDIS_CONTAINER = os.environ.get("REDIS_CONTAINER", "prometheus_redis")
MGET_CHUNK = 80


def log(msg: str) -> None:
    print(msg, flush=True)


def redis_pw() -> str:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("REDIS_PASSWORD="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("REDIS_PASSWORD yok")


RP = redis_pw()


def rc(*args: str, timeout: int = 180) -> str:
    cmd = [
        "docker", "exec", REDIS_CONTAINER,
        "redis-cli", "-a", RP, "--no-auth-warning", *args,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 and r.stderr:
        raise RuntimeError(r.stderr[:200])
    return (r.stdout or "").strip()


def mget_map(keys: list[str], label: str = "") -> dict[str, str | None]:
    """Toplu MGET — her anahtar icin ayri docker exec YOK."""
    out: dict[str, str | None] = {}
    total = len(keys)
    for i in range(0, total, MGET_CHUNK):
        chunk = keys[i : i + MGET_CHUNK]
        if label and total > MGET_CHUNK:
            log(f"  ... {label} {min(i + MGET_CHUNK, total)}/{total}")
        raw = rc("MGET", *chunk)
        vals = raw.splitlines() if raw else []
        if len(vals) != len(chunk):
            vals = vals + ["(nil)"] * (len(chunk) - len(vals))
        for k, v in zip(chunk, vals):
            out[k] = None if v in ("(nil)", "", None) else v
    return out


def jparse(raw: str | None) -> dict | list | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def classify_shadow_block(
    sig: dict | None, sym: str, cooled: bool, open_n: int, max_open: int,
) -> str:
    try:
        import sys
        sys.path.insert(0, str(ROOT / "services" / "shared"))
        from profit_rules import is_blacklisted
        if is_blacklisted(sym):
            return "blacklist"
    except Exception:
        pass
    if cooled:
        return "cooldown_aktif"
    if open_n >= max_open:
        return f"max_acik_{open_n}/{max_open}"
    if not sig:
        return "sinyal_yok"
    if sig.get("direction") == "flat":
        return "sinyal_flat"
    if not sig.get("is_valid"):
        rr = sig.get("reject_reason") or "gecersiz"
        return f"reddedildi:{str(rr)[:50]}"
    conf = float(sig.get("confidence", 0))
    if conf < 0.60:
        return f"shadow_min_conf_{conf:.2f}"
    dec = sig.get("decision") or {}
    sl = float(dec.get("stop_loss_pct") or sig.get("stop_loss_pct") or 1.2)
    tp_list = dec.get("take_profit_tiers_pct") or sig.get("take_profit_tiers") or [1.5]
    tp = float(tp_list[0] if tp_list else 1.5)
    if sl > 0 and tp / sl < 1.25:
        return f"rr_dusuk_{tp/sl:.2f}"
    return "ALIM_UYGUN"


def main() -> None:
    t0 = time.time()
    log("=" * 72)
    log("  DERIN KARLILIK TESHISI — pipeline + karar + sonuc")
    log("=" * 72)

    log("\n[0] Redis baglantisi...")
    ping = rc("PING")
    if "PONG" not in ping:
        raise SystemExit(f"Redis PONG yok: {ping}")
    log(f"  OK ({REDIS_CONTAINER})")

    log("\n[0b] Meta veriler okunuyor...")
    meta_keys = [
        "portfolio:state:v1",
        "snapshot:universe:v1",
        "system:risk_limits:v1",
        "system:promotion:status",
        "system:trading:halted",
        "signal_engine:stats",
        "guard:status:v1",
    ]
    meta_raw = mget_map(meta_keys)
    portfolio = jparse(meta_raw.get("portfolio:state:v1")) or {}
    universe = jparse(meta_raw.get("snapshot:universe:v1")) or {}
    risk = jparse(meta_raw.get("system:risk_limits:v1")) or {}
    halted = jparse(meta_raw.get("system:trading:halted")) or {}
    sig_stats = jparse(meta_raw.get("signal_engine:stats")) or {}
    guard_status = jparse(meta_raw.get("guard:status:v1")) or {}
    uni_counts = universe.get("counts") or {}
    symbols: list[str] = list(universe.get("symbols") or [])
    if not symbols:
        log("  UYARI: snapshot:universe bos — KEYS ile sembol araniyor...")
        kraw = rc("KEYS", "features:latest:*")
        symbols = sorted(
            ln.replace("features:latest:", "").upper()
            for ln in (kraw.splitlines() if kraw else [])
            if ln and ln != "(nil)"
        )[:600]

    log(f"  {len(symbols)} sembol bulundu")

    log("\n[1] SISTEM DURUMU")
    log(f"  Max acik pozisyon: {risk.get('max_open_positions', '?')}")
    log(f"  Min sinyal conf:   {float(risk.get('min_signal_confidence', 0))*100:.0f}%")
    log(f"  Shadow max open:   3")
    log(f"  Min shadow conf:   62%")
    log(f"  Cooldown:          1800 sn (30 dk)")
    log(f"  Trading halted:    {halted.get('halted', False)}")
    log(f"  Acik pozisyon:     {portfolio.get('total_open', 0)} "
        f"(oms={portfolio.get('oms_open', 0)} shadow={portfolio.get('shadow_open', 0)})")
    log(f"  Evren boyutu:      {len(symbols)} sembol")
    if uni_counts:
        log(f"  Evren ozet:        long={uni_counts.get('long',0)} short={uni_counts.get('short',0)} "
            f"flat={uni_counts.get('flat',0)} close_act={uni_counts.get('close_actions',0)}")
    if guard_status:
        log(f"  Guard aktif:       {guard_status.get('active', False)} "
            f"izlenen={guard_status.get('count', 0)} pozisyon")

    log("\n[2] PIPELINE HUNISI")
    log(f"  features/signal:   {len(symbols)} (evren snapshot)")
    log(f"  Gecerli long:      {uni_counts.get('long', '?')}")
    log(f"  Gecerli short:     {uni_counts.get('short', '?')}")

    log("\n[3] TUM SINYALLER — toplu okuma (MGET)...")
    sig_keys = [f"signal:latest:{s}" for s in symbols]
    sig_raw_map = mget_map(sig_keys, "sinyal")
    signals: dict[str, dict] = {}
    reject_ctr: Counter = Counter()
    dir_ctr: Counter = Counter()
    conf_buckets: Counter = Counter()
    valid_long = valid_short = 0
    near_miss: list[tuple] = []

    for sym in symbols:
        sig = jparse(sig_raw_map.get(f"signal:latest:{sym}"))
        if not sig:
            continue
        signals[sym] = sig
        d = str(sig.get("direction", "flat"))
        dir_ctr[d] += 1
        conf = float(sig.get("confidence", 0))
        if conf < 0.58:
            conf_buckets["<58%"] += 1
        elif conf < 0.62:
            conf_buckets["58-62%"] += 1
        elif conf < 0.70:
            conf_buckets["62-70%"] += 1
        else:
            conf_buckets[">=70%"] += 1
        if sig.get("is_valid") and d == "long":
            valid_long += 1
        if sig.get("is_valid") and d == "short":
            valid_short += 1
        if not sig.get("is_valid"):
            reason = str(sig.get("reject_reason") or "bilinmiyor")[:80]
            reject_ctr[reason] += 1
            if conf >= 0.55 and d in ("long", "short"):
                near_miss.append((sym, d, conf, reason))

    log(f"  Okunan sinyal:     {len(signals)}/{len(symbols)}")
    log(f"  Gecerli LONG:      {valid_long}")
    log(f"  Gecerli SHORT:     {valid_short}")
    log(f"  Yon dagilimi:      {dict(dir_ctr)}")
    log(f"  Conf dagilimi:     {dict(conf_buckets)}")
    log("  Red nedenleri (top 12):")
    for reason, n in reject_ctr.most_common(12):
        log(f"    {n:4d}x  {reason}")

    if sig_stats:
        wr_vals = [
            float(v.get("win_rate", 0))
            for v in sig_stats.values()
            if int(v.get("trades", 0) or 0) > 3
        ]
        if wr_vals:
            log(f"  Signal stats WR:   {sum(wr_vals)/len(wr_vals)*100:.1f}% "
                f"({len(sig_stats)} sembol kayitli)")

    open_n = int(portfolio.get("shadow_open", 0) or 0)
    max_open = 3
    sample_syms = symbols[-50:] if len(symbols) >= 50 else symbols

    log(f"\n[4] SON {len(sample_syms)} COIN — KARAR ZINCIRI")
    log(f"  {'SYMBOL':14s} {'SIG':5s} {'CONF':6s} {'AGENT':6s} {'LEARN':8s} {'SHADOW':22s} {'FIYAT':>8s}")
    log("  " + "-" * 72)

    detail_keys: list[str] = []
    for sym in sample_syms:
        detail_keys.extend([
            f"agents:verdict:{sym}",
            f"learn:profile:{sym}",
            f"binance:ticker:{sym.lower()}",
            f"trade:cooldown:shadow:{sym.upper()}",
        ])
    log("  Agent/learn/fiyat okunuyor...")
    detail_raw = mget_map(detail_keys, "detay")

    open_positions = {p["symbol"]: p for p in (portfolio.get("positions") or [])}
    alim_uygun = 0
    block_ctr: Counter = Counter()

    for sym in sample_syms:
        sig = signals.get(sym)
        verdict = jparse(detail_raw.get(f"agents:verdict:{sym}")) or {}
        learn = jparse(detail_raw.get(f"learn:profile:{sym}")) or {}
        cd_raw = detail_raw.get(f"trade:cooldown:shadow:{sym.upper()}")
        cooled = False
        if cd_raw:
            try:
                cooled = time.time() < float(cd_raw)
            except (TypeError, ValueError):
                pass

        v_dir = str(verdict.get("direction", verdict.get("verdict", "?")))[:5]
        learn_hint = str(learn.get("avoid_hint", "") or "-")[:8]
        sig_dir = str(sig.get("direction", "?"))[:5] if sig else "?"
        conf = float(sig.get("confidence", 0)) if sig else 0
        block = classify_shadow_block(sig, sym, cooled, open_n, max_open)
        if sym in open_positions:
            block = f"ACIK_{open_positions[sym].get('direction', '?')}"
        block_ctr[block.split(":")[0] if ":" in block else block] += 1
        if block == "ALIM_UYGUN":
            alim_uygun += 1

        ticker = jparse(detail_raw.get(f"binance:ticker:{sym.lower()}"))
        price = 0.0
        if ticker:
            td = ticker.get("data", ticker)
            price = float(td.get("b", td.get("c", 0)) or 0)

        reject = ""
        if sig and not sig.get("is_valid"):
            reject = str(sig.get("reject_reason", ""))[:30]

        log(
            f"  {sym:14s} {sig_dir:5s} {conf:5.0%} {v_dir:6s} {learn_hint:8s} "
            f"{block:22s} {price:8.4f}"
            + (f"  | {reject}" if reject else "")
        )

    log(f"\n  Ozet: {alim_uygun}/{len(sample_syms)} ALIM_UYGUN")
    log("  Blokaj dagilimi:")
    for b, n in block_ctr.most_common(8):
        log(f"    {n:3d}x  {b}")
    if open_n >= max_open:
        log(f"  !! Shadow dolu ({open_n}/{max_open}) — yeni alim BLOKE")

    if near_miss:
        log(f"\n[5] YAKIN KACANLAR (conf>=55%, reddedildi) — {len(near_miss)} adet")
        for sym, d, c, r in sorted(near_miss, key=lambda x: -x[2])[:15]:
            log(f"    {sym:14s} {d:5s} conf={c:.0%}  {r[:55]}")

    log("\n[6] ISLEM GECMISI okunuyor...")
    raw_trades = rc("LRANGE", "oms:trade_history", "0", "499")
    all_trades: list[dict] = []
    for line in raw_trades.splitlines():
        try:
            all_trades.append(json.loads(line.strip()))
        except json.JSONDecodeError:
            pass
    all_trades.sort(key=lambda t: float(t.get("closed_at", 0)), reverse=True)

    log(f"\n[6a] SON 20 ISLEM — AL → TUT → SAT")
    log(f"  {'SYMBOL':12s} {'YON':5s} {'PNL':>8s} {'$PNL':>9s} {'TUTMA':>7s} {'CIKIS NEDENI':42s}")
    log("  " + "-" * 78)
    for t in all_trades[:20]:
        sym = str(t.get("symbol", "?"))[:12]
        direction = str(t.get("direction", "?"))[:5]
        pnl = float(t.get("pnl_pct", 0))
        pnl_u = float(t.get("pnl_usdt", 0))
        hold = int(float(t.get("hold_seconds", 0)))
        exit_r = str(t.get("exit_reason") or t.get("close_reason") or "?")[:42]
        ladder = t.get("ladder") or {}
        entry_c = float(ladder.get("entry_confidence", 0) or 0)
        sl = ladder.get("stop_loss_pct", "?")
        tp = ladder.get("take_profit_pct", "?")
        log(f"  {sym:12s} {direction:5s} {pct(pnl):>8s} ${pnl_u:+8.2f} {hold:6d}s  {exit_r}")
        if entry_c:
            log(f"             giris conf={entry_c:.0%} sl={sl}% tp={tp}% tier={ladder.get('tier',1)}")

    for sid in ("SHADOW_A", "SHADOW_B", "SHADOW_C"):
        st_raw = rc("LRANGE", f"shadow:trades:{sid}", "0", "4")
        st: list[dict] = []
        for line in st_raw.splitlines():
            try:
                st.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                pass
        if st:
            log(f"\n[6b] SON 5 SHADOW — {sid}")
            for t in st[:5]:
                ex = str(t.get("exit_reason") or t.get("close_reason") or "?")[:45]
                log(f"  {t.get('symbol','?'):12s} {pct(float(t.get('pnl_pct',0))):>8s} "
                    f"{int(float(t.get('hold_seconds',0))):5d}s  {ex}")

    log(f"\n[7] ACIK POZISYONLAR ({len(portfolio.get('positions') or [])})")
    open_syms = [p.get("symbol") for p in (portfolio.get("positions") or []) if p.get("symbol")]
    open_ticker_keys = [
        f"binance:ticker:{s.lower()}" for s in open_syms
        if f"binance:ticker:{s.lower()}" not in detail_raw
    ]
    if open_ticker_keys:
        detail_raw.update(mget_map(open_ticker_keys, "acik-ticker"))

    for p in portfolio.get("positions") or []:
        sym = p.get("symbol", "?")
        sig = signals.get(sym) or {}
        verdict = jparse(detail_raw.get(f"agents:verdict:{sym}")) or {}
        learn = jparse(detail_raw.get(f"learn:profile:{sym}")) or {}
        entry = float(p.get("entry_price", 0))
        ticker = jparse(detail_raw.get(f"binance:ticker:{sym.lower()}"))
        price = 0.0
        if ticker:
            td = ticker.get("data", ticker)
            bid = float(td.get("b", 0) or 0)
            ask = float(td.get("a", bid) or bid)
            price = (bid + ask) / 2 if bid and ask else bid
        upnl = 0.0
        if entry > 0 and price > 0:
            upnl = (
                (price - entry) / entry * 100
                if p.get("direction") == "long"
                else (entry - price) / entry * 100
            )
        log(f"  {sym} {p.get('direction')} [{p.get('source')}] "
            f"entry={entry:.4f} now={price:.4f} upnl={upnl:+.2f}%")
        log(f"    sinyal={sig.get('direction','?')} conf={float(sig.get('confidence',0)):.0%} "
            f"action={sig.get('trade_action','?')}")
        log(f"    agent={verdict.get('direction','?')} conf={float(verdict.get('confidence',0)):.0%}")
        if learn.get("avoid_hint"):
            log(f"    learn: {str(learn.get('avoid_hint'))[:70]}")

    feed_raw = rc("LRANGE", "activity:feed", "0", "19")
    log(f"\n[8] SON AKTIVITE")
    for line in feed_raw.splitlines()[:12]:
        try:
            ev = json.loads(line.strip())
            log(f"  {ev.get('type','?'):12s} {str(ev.get('symbol','')):12s} "
                f"{str(ev.get('reason', ev.get('msg', '')))[:55]}")
        except json.JSONDecodeError:
            pass

    if all_trades:
        chron = sorted(all_trades, key=lambda t: float(t.get("closed_at", 0)))
        recent = chron[-50:]
        old = chron[:-50]
        def wr(ts: list[dict]) -> float:
            return sum(1 for t in ts if float(t.get("pnl_pct", 0)) > 0) / len(ts) if ts else 0.0

        log(f"\n[9] KARLILIK OZET (son {len(chron)} islem)")
        log(f"  Win rate tumu:    {wr(chron)*100:.1f}%")
        log(f"  Win rate son 50:  {wr(recent)*100:.1f}%")
        if old:
            log(f"  Win rate eski:    {wr(old)*100:.1f}%")
        sym_pnl: dict[str, float] = defaultdict(float)
        for t in chron:
            sym_pnl[str(t.get("symbol", "?"))] += float(t.get("pnl_usdt", 0))
        ranked = sorted(sym_pnl.items(), key=lambda x: x[1])
        log("  En kotu 5 sembol:")
        for sym, pnl in ranked[:5]:
            log(f"    {sym:14s} ${pnl:+.2f}")
        log("  En iyi 5 sembol:")
        for sym, pnl in ranked[-5:][::-1]:
            log(f"    {sym:14s} ${pnl:+.2f}")

        empty_exit = sum(
            1 for t in chron
            if not str(t.get("exit_reason") or t.get("close_reason") or "").strip()
        )
        if empty_exit:
            log(f"  UYARI: {empty_exit}/{len(chron)} islemde cikis nedeni bos")

    log("\n[10] GELISTIRME ONERILERI")
    issues: list[str] = []
    if open_n >= max_open:
        issues.append("Shadow dolu → yeni alim yok; pozisyonlar kapanana kadar bekle")
    if valid_long + valid_short < 5:
        issues.append("Cok az gecerli sinyal → agent/feature pipeline veya conf esigi")
    flat_n = dir_ctr.get("flat", 0)
    if flat_n > len(signals) * 0.4:
        issues.append(f"Sinyallerin %{flat_n*100//max(len(signals),1)} flat — ensemble temkinli")
    top_reject = reject_ctr.most_common(1)
    if top_reject:
        issues.append(f"En sik red: {top_reject[0][1]}x '{top_reject[0][0][:50]}'")
    if block_ctr.get("cooldown_aktif", 0) > 10:
        issues.append(f"{block_ctr['cooldown_aktif']} coin cooldown'da — churn sonrasi 30dk bekleme")
    bad_syms = {"ESPORTSUSDT", "GTCUSDT", "DEXEUSDT", "AIOUSDT", "BRUSDT"}
    bad_hit = [s for s in sample_syms if s in bad_syms]
    if bad_hit:
        issues.append(f"Zararli coinler evrende: {', '.join(bad_hit[:5])} → blacklist dusun")
    if not issues:
        issues.append("Pipeline calisiyor; son 50 WR iyilesiyorsa paper devam")
    for i, msg in enumerate(issues, 1):
        log(f"  {i}. {msg}")

    elapsed = time.time() - t0
    log(f"\n  Sure: {elapsed:.1f} sn")
    log("=" * 72)


if __name__ == "__main__":
    main()
