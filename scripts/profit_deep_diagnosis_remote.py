#!/usr/bin/env python3
"""
VPS uzerinde calisir — Redis pipeline + karlilik derin analiz (genisletilmis).
Hiz: docker exec prometheus_redis + toplu MGET.
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

CRITICAL_SERVICES = (
    "data_ingestion", "feature_engine", "context_engine", "signal_engine",
    "agent_system", "shadow_system", "oms", "immunity_system",
)


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


def shell(cmd: str) -> str:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return ((r.stdout or "") + (r.stderr or "")).strip()


def load_profit_rules() -> dict:
    try:
        sys.path.insert(0, str(ROOT / "services" / "shared"))
        import profit_rules as pr  # noqa: WPS433

        return {
            "shadow_min_conf": pr.SHADOW_MIN_CONFIDENCE,
            "oms_min_conf": pr.OMS_MIN_CONFIDENCE,
            "paper_min_conf": pr.PAPER_MIN_SIGNAL_CONFIDENCE,
            "shadow_max_open": pr.SHADOW_MAX_OPEN,
            "max_hold_sec": pr.MAX_POSITION_HOLD_SEC,
            "stale_verdict_sec": pr.STALE_VERDICT_HOLD_SEC,
            "cooldown_sec": pr.PAPER_SYMBOL_COOLDOWN_SEC,
            "blacklist": sorted(pr.SYMBOL_BLACKLIST),
        }
    except Exception as exc:
        return {"error": str(exc)}


def ticker_price(raw: str | None, feat_raw: str | None = None, klines_raw: str | None = None) -> float:
    t = jparse(raw)
    if t:
        td = t.get("data", t) if isinstance(t, dict) else {}
        bid = float(td.get("b", td.get("c", 0)) or 0)
        ask = float(td.get("a", bid) or bid)
        if bid > 0:
            return (bid + ask) / 2 if ask else bid
    feat = jparse(feat_raw)
    if feat:
        for key in ("close", "last_price", "mark_price"):
            p = float(feat.get(key, 0) or 0)
            if p > 0:
                return p
    kl = jparse(klines_raw)
    if isinstance(kl, list) and kl:
        last = kl[-1]
        if isinstance(last, dict):
            p = float(last.get("close", 0) or 0)
            if p > 0:
                return p
    return 0.0


def classify_shadow_block(
    sig: dict | None,
    sym: str,
    cooled: bool,
    open_n: int,
    max_open: int,
    rules: dict,
) -> str:
    try:
        sys.path.insert(0, str(ROOT / "services" / "shared"))
        from profit_rules import is_blacklisted  # noqa: WPS433

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
    min_c = float(rules.get("shadow_min_conf", 0.60))
    if conf < min_c:
        return f"shadow_min_conf_{conf:.2f}"
    dec = sig.get("decision") or {}
    sl = float(dec.get("stop_loss_pct") or sig.get("stop_loss_pct") or 1.2)
    tp_list = dec.get("take_profit_tiers_pct") or sig.get("take_profit_tiers") or [1.5]
    tp = float(tp_list[0] if tp_list else 1.5)
    if sl > 0 and tp / sl < 1.25:
        return f"rr_dusuk_{tp/sl:.2f}"
    return "ALIM_UYGUN"


def parse_risk_limits(risk: dict) -> dict:
    max_lev = float(risk.get("max_leverage", 3) or 3)
    max_pos = float(risk.get("max_position_pct", 0.05) or 0.05)
    if max_pos > 1:
        max_pos = max_pos / 100 if max_pos <= 100 else 0.05
    return {
        "max_leverage": min(max_lev, 3.0),
        "max_position_pct": max_pos,
        "max_open_positions": int(risk.get("max_open_positions", 30) or 30),
    }


def portfolio_value_usd(portfolio: dict) -> float:
    for key in ("equity", "current_equity", "portfolio_value"):
        v = float(portfolio.get(key, 0) or 0)
        if v > 0:
            return v
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("PORTFOLIO_VALUE="):
            try:
                return float(line.split("=", 1)[1].strip().strip('"').strip("'"))
            except ValueError:
                break
    return 10_000.0


def expected_shadow_size(
    pv: float,
    max_open: int,
    max_pos_pct: float,
    confidence: float,
    leverage: float,
    open_n: int,
) -> float:
    slot_budget = pv / max(max_open, 1)
    base_usd = min(pv * max_pos_pct, slot_budget * 0.92)
    size = base_usd * min(confidence, 0.85) * min(leverage / 3.0, 1.0)
    if open_n >= max_open * 0.8:
        size *= 0.85
    return size


def trade_side_label(direction: str) -> str:
    return "BUY" if direction == "long" else "SELL_SHORT"


def close_side_label(direction: str) -> str:
    return "SELL" if direction == "long" else "BUY_COVER"


def audit_position_decision(
    pos: dict,
    ladder: dict,
    sig: dict | None,
    rules: dict,
    risk_lim: dict,
    pv: float,
    price: float,
    hold: int,
    max_hold: int,
) -> dict:
    direction = str(pos.get("direction", "long"))
    size = float(pos.get("size_usd", 0) or 0)
    entry = float(pos.get("entry_price", pos.get("price", 0)) or 0)
    min_c = float(rules.get("shadow_min_conf", 0.62))
    max_pos = float(risk_lim.get("max_position_pct", 0.05))
    max_lev = float(risk_lim.get("max_leverage", 3))

    entry_conf = float(ladder.get("entry_confidence", 0) or 0)
    if not entry_conf and sig:
        entry_conf = float(sig.get("confidence", 0) or 0)
    lev = float(ladder.get("leverage", max_lev) or max_lev)
    port_pct = float(ladder.get("position_size_pct", 0) or 0)
    if port_pct <= 0 and pv > 0 and size > 0:
        port_pct = size / pv
    notional = float(ladder.get("notional_usd", 0) or 0)
    if notional <= 0 and size > 0:
        notional = size * lev

    sl = float(ladder.get("stop_loss_pct", 0) or 0)
    tp = float(ladder.get("take_profit_pct", 0) or 0)
    if not sl and sig:
        dec = sig.get("decision") or {}
        sl = float(dec.get("stop_loss_pct") or sig.get("stop_loss_pct") or 1.2)
    if not tp and sig:
        dec = sig.get("decision") or {}
        tp_list = dec.get("take_profit_tiers_pct") or sig.get("take_profit_tiers") or [1.5]
        tp = float(tp_list[0] if tp_list else 1.5)
    rr = tp / sl if sl > 0 else 0

    upnl = 0.0
    if entry > 0 and price > 0:
        upnl = (
            (price - entry) / entry * 100
            if direction == "long"
            else (entry - price) / entry * 100
        )

    checks: list[str] = []
    if entry_conf >= min_c:
        checks.append("conf_OK")
    elif entry_conf > 0:
        checks.append(f"conf_dusuk_{entry_conf:.0%}")
    else:
        checks.append("conf_eski_kayit")

    if port_pct <= max_pos * 1.12:
        checks.append("size_OK")
    elif port_pct > 0:
        checks.append(f"size_yuksek_{port_pct:.1%}")

    if rr >= 1.25 or rr == 0:
        checks.append("rr_OK" if rr >= 1.25 else "rr_bilinmiyor")
    else:
        checks.append(f"rr_dusuk_{rr:.2f}")

    if lev <= 3:
        checks.append(f"lev_{lev:.0f}x_OK")
    else:
        checks.append(f"lev_{lev:.0f}x_ASIRI")

    sig_dir = str((sig or {}).get("direction", "?"))
    if sig_dir in ("long", "short") and sig_dir != direction:
        checks.append("UYARI_sinyal_ters")
    elif sig_dir == direction:
        checks.append("yon_OK")

    exit_next: list[str] = []
    if sl > 0:
        exit_next.append(f"stop@{-sl:.1f}% (simdi {upnl:+.2f}%)")
    if tp > 0:
        exit_next.append(f"tp@+{tp:.1f}% (simdi {upnl:+.2f}%)")
    if ladder.get("breakeven_armed"):
        exit_next.append("breakeven_aktif")
    if hold >= max_hold:
        exit_next.append("max_hold_TETIK")
    elif max_hold - hold < 600:
        exit_next.append(f"max_hold_{max_hold - hold}s")
    stale = int(rules.get("stale_verdict_sec", 1200))
    if sig_dir == "flat" and hold >= stale:
        exit_next.append("stale_flat_HAZIR")

    ok_count = sum(1 for c in checks if c.endswith("_OK") or "lev_" in c and "_OK" in c)
    verdict = "DOGRU" if ok_count >= 4 and "UYARI" not in " ".join(checks) else "KONTROL"

    return {
        "direction": direction,
        "side": trade_side_label(direction),
        "close_side": close_side_label(direction),
        "size": size,
        "port_pct": port_pct,
        "leverage": lev,
        "notional": notional,
        "sl": sl,
        "tp": tp,
        "rr": rr,
        "entry_conf": entry_conf,
        "upnl": upnl,
        "checks": checks,
        "exit_next": exit_next,
        "verdict": verdict,
        "risk_reasons": ladder.get("risk_reasons") or [],
        "kelly": float(ladder.get("kelly_fraction", 0) or 0),
    }


def decision_row(
    sym: str,
    sig: dict | None,
    verdict: dict,
    learn: dict,
    block: str,
    price: float,
    extra: str = "",
) -> str:
    sig_dir = str(sig.get("direction", "?"))[:5] if sig else "?"
    conf = float(sig.get("confidence", 0)) if sig else 0
    v_dir = str(verdict.get("direction", verdict.get("verdict", "?")))[:6]
    v_conf = float(verdict.get("confidence", 0))
    learn_hint = str(learn.get("avoid_hint", "") or learn.get("regime", "") or "-")[:10]
    reject = ""
    if sig and not sig.get("is_valid"):
        reject = str(sig.get("reject_reason", ""))[:28]
    line = (
        f"  {sym:14s} {sig_dir:5s} {conf:5.0%} {v_dir:6s} {v_conf:4.0%} "
        f"{learn_hint:10s} {block:22s} {price:8.4f}"
    )
    if reject:
        line += f"  | {reject}"
    if extra:
        line += f"  | {extra}"
    return line


def main() -> None:
    t0 = time.time()
    rules = load_profit_rules()
    max_open = int(rules.get("shadow_max_open", 3))
    max_hold = int(rules.get("max_hold_sec", 3600))

    log("=" * 72)
    log("  DERIN KARLILIK TESHISI — tam pipeline + karar + sonuc")
    log("=" * 72)

    log("\n[0] Redis baglantisi...")
    if "PONG" not in rc("PING"):
        raise SystemExit("Redis PONG yok")
    log(f"  OK ({REDIS_CONTAINER})")

    log("\n[0b] Sunucu + servis nabzi...")
    uptime = shell("uptime 2>/dev/null | tail -1")
    if uptime:
        log(f"  {uptime}")
    hb_keys = [f"system:heartbeat:{s}" for s in CRITICAL_SERVICES]
    hb_raw = mget_map(hb_keys)
    now = time.time()
    for svc in CRITICAL_SERVICES:
        raw = hb_raw.get(f"system:heartbeat:{svc}")
        if not raw:
            log(f"  !! {svc:18s} heartbeat YOK")
            continue
        try:
            age = now - float(raw)
            mark = "OK" if age < 120 else "ESKI"
            log(f"  {mark:3s} {svc:18s} {int(age)}s once")
        except (TypeError, ValueError):
            log(f"  ?   {svc:18s} {raw[:20]}")

    log("\n[0c] Meta veriler...")
    meta_keys = [
        "portfolio:state:v1",
        "snapshot:universe:v1",
        "system:risk_limits:v1",
        "system:promotion:status",
        "system:trading:halted",
        "signal_engine:stats",
        "guard:status:v1",
        "system:deploy:version",
        "shadow:leaderboard",
        "ws:status",
    ]
    meta_raw = mget_map(meta_keys)
    portfolio = jparse(meta_raw.get("portfolio:state:v1")) or {}
    universe = jparse(meta_raw.get("snapshot:universe:v1")) or {}
    risk = jparse(meta_raw.get("system:risk_limits:v1")) or {}
    halted = jparse(meta_raw.get("system:trading:halted")) or {}
    sig_stats = jparse(meta_raw.get("signal_engine:stats")) or {}
    guard_status = jparse(meta_raw.get("guard:status:v1")) or {}
    deploy = jparse(meta_raw.get("system:deploy:version")) or {}
    leaderboard = jparse(meta_raw.get("shadow:leaderboard")) or {}
    ws_status = jparse(meta_raw.get("ws:status")) or {}

    risk_lim = parse_risk_limits(risk)
    pv = portfolio_value_usd(portfolio)

    uni_counts = universe.get("counts") or {}
    symbols: list[str] = list(universe.get("symbols") or [])
    if not symbols:
        kraw = rc("KEYS", "features:latest:*")
        symbols = sorted(
            ln.replace("features:latest:", "").upper()
            for ln in (kraw.splitlines() if kraw else [])
            if ln and ln != "(nil)"
        )[:600]
    log(f"  {len(symbols)} sembol")

    log("\n[1] SISTEM DURUMU + KURALLAR")
    log(f"  Paper min conf:    {float(rules.get('paper_min_conf', 0.57))*100:.0f}%")
    log(f"  Shadow min conf:   {float(rules.get('shadow_min_conf', 0.60))*100:.0f}%")
    log(f"  OMS min conf:      {float(rules.get('oms_min_conf', 0.58))*100:.0f}%")
    log(f"  Shadow max open:   {max_open}")
    log(f"  Max tutma:         {max_hold}s ({max_hold//60} dk)")
    log(f"  Stale verdict:     {rules.get('stale_verdict_sec', 1200)}s")
    log(f"  Cooldown:          {rules.get('cooldown_sec', 600)}s")
    if rules.get("blacklist"):
        log(f"  Blacklist:         {', '.join(rules['blacklist'][:8])}")
    log(f"  Max leverage:      {risk_lim['max_leverage']:.0f}x (immunity cap 3x)")
    log(f"  Max pozisyon:      {risk_lim['max_position_pct']*100:.1f}% portfoy / islem")
    log(f"  Portfoy baz:       ${pv:,.0f}")
    log(f"  Slot butcesi:      ${pv / max(max_open, 1):,.0f} (portfoy/{max_open})")
    log(f"  Trading halted:    {halted.get('halted', False)}")
    log(f"  WS:                {ws_status.get('status', '?')} "
        f"({ws_status.get('symbols', '?')} sembol)")
    if deploy:
        log(f"  Son deploy:        {deploy.get('deployed_at_iso', '?')} "
            f"v{deploy.get('version', '?')[:24]}")
    open_n = int(portfolio.get("shadow_open", 0) or 0)
    log(f"  Acik pozisyon:     {portfolio.get('total_open', 0)} "
        f"(oms={portfolio.get('oms_open', 0)} shadow={open_n})")
    eq = float(portfolio.get("equity", portfolio.get("current_equity", 0)) or 0)
    pnl = float(portfolio.get("total_pnl", portfolio.get("daily_pnl", 0)) or 0)
    if eq:
        log(f"  Equity:            ${eq:,.2f}  gunluk PnL=${pnl:+,.2f}")
    log(f"  Evren:             long={uni_counts.get('long',0)} short={uni_counts.get('short',0)} "
        f"flat={uni_counts.get('flat',0)}")

    log("\n[2] PIPELINE HUNISI (sayim)")
    sig_keys = [f"signal:latest:{s}" for s in symbols]
    feat_keys = [f"features:latest:{s}" for s in symbols]
    sig_raw_map = mget_map(sig_keys, "sinyal")
    feat_raw_map = mget_map(feat_keys, "feature")

    signals: dict[str, dict] = {}
    features: dict[str, dict] = {}
    reject_ctr: Counter = Counter()
    dir_ctr: Counter = Counter()
    conf_buckets: Counter = Counter()
    valid_long: list[tuple[str, float]] = []
    valid_short: list[tuple[str, float]] = []
    near_miss: list[tuple] = []
    no_feature = no_signal = 0

    for sym in symbols:
        feat = jparse(feat_raw_map.get(f"features:latest:{sym}"))
        if feat:
            features[sym] = feat
        else:
            no_feature += 1
        sig = jparse(sig_raw_map.get(f"signal:latest:{sym}"))
        if not sig:
            no_signal += 1
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
            valid_long.append((sym, conf))
        if sig.get("is_valid") and d == "short":
            valid_short.append((sym, conf))
        if not sig.get("is_valid"):
            reason = str(sig.get("reject_reason") or "bilinmiyor")[:80]
            reject_ctr[reason] += 1
            if conf >= 0.55 and d in ("long", "short"):
                near_miss.append((sym, d, conf, reason))

    valid_long.sort(key=lambda x: -x[1])
    valid_short.sort(key=lambda x: -x[1])

    log(f"  features:          {len(features)}/{len(symbols)} ({no_feature} eksik)")
    log(f"  signal:            {len(signals)}/{len(symbols)} ({no_signal} eksik)")
    log(f"  gecerli LONG:      {len(valid_long)}")
    log(f"  gecerli SHORT:     {len(valid_short)}")
    log(f"  yon:               {dict(dir_ctr)}")
    log(f"  conf:              {dict(conf_buckets)}")
    log("  red (top 8):")
    for reason, n in reject_ctr.most_common(8):
        log(f"    {n:4d}x  {reason}")

    log("\n[3] GECERLI SINYALLER — TAM LISTE")
    log(f"  {'SYMBOL':14s} {'YON':5s} {'CONF':6s} {'LEV':4s} {'REGIME':12s} {'CRISIS':6s}")
    log("  " + "-" * 58)
    detail_syms = [s for s, _ in valid_long[:15]] + [s for s, _ in valid_short[:15]]
    detail_keys: list[str] = []
    for sym in detail_syms:
        detail_keys.extend([
            f"agents:verdict:{sym}",
            f"context:latest:{sym}",
            f"learn:profile:{sym}",
            f"binance:ticker:{sym.lower()}",
            f"trade:cooldown:shadow:{sym.upper()}",
        ])
    detail_raw = mget_map(detail_keys, "gecerli-detay")

    def ctx_fields(sym: str) -> tuple[str, str]:
        ctx = jparse(detail_raw.get(f"context:latest:{sym}")) or {}
        feat = features.get(sym) or {}
        regime = str(
            ctx.get("regime")
            or ctx.get("regime_label")
            or feat.get("regime")
            or feat.get("regime_label")
            or "?"
        )[:12]
        crisis = ctx.get("crisis_level", feat.get("crisis_level", feat.get("vix_proxy", "?")))
        return regime, str(crisis)

    for sym, conf in valid_long[:15]:
        regime, crisis = ctx_fields(sym)
        sig = signals.get(sym) or {}
        lev = int(sig.get("leverage") or (sig.get("risk") or {}).get("recommended_leverage") or 1)
        log(f"  {sym:14s} long  {conf:5.0%} {lev:3d}x {regime:12s} {crisis}")
    for sym, conf in valid_short[:15]:
        regime, crisis = ctx_fields(sym)
        sig = signals.get(sym) or {}
        lev = int(sig.get("leverage") or (sig.get("risk") or {}).get("recommended_leverage") or 1)
        log(f"  {sym:14s} short {conf:5.0%} {lev:3d}x {regime:12s} {crisis}")

    log("\n[4] ALIM KAPISI — TUM EVREN TARAMASI")
    open_positions = {p["symbol"]: p for p in (portfolio.get("positions") or [])}
    cd_keys = [f"trade:cooldown:shadow:{s.upper()}" for s in symbols]
    cd_map = mget_map(cd_keys, "cooldown")
    block_all: Counter = Counter()
    alim_uygun_list: list[tuple[str, str, float]] = []

    for sym in symbols:
        sig = signals.get(sym)
        cd_raw = cd_map.get(f"trade:cooldown:shadow:{sym.upper()}")
        cooled = False
        if cd_raw:
            try:
                cooled = time.time() < float(cd_raw)
            except (TypeError, ValueError):
                pass
        block = classify_shadow_block(sig, sym, cooled, open_n, max_open, rules)
        if sym in open_positions:
            block = f"ACIK_{open_positions[sym].get('direction', '?')}"
        key = block.split(":")[0] if ":" in block else block
        block_all[key] += 1
        if block == "ALIM_UYGUN":
            d = str(sig.get("direction", "?")) if sig else "?"
            c = float(sig.get("confidence", 0)) if sig else 0
            alim_uygun_list.append((sym, d, c))

    log(f"  ALIM_UYGUN:        {len(alim_uygun_list)} sembol")
    if open_n >= max_open:
        log(f"  !! BLOKE: Shadow dolu ({open_n}/{max_open}) — uygun sinyal olsa da ALIM YOK")
    log("  Blokaj (tum evren):")
    for b, n in block_all.most_common(10):
        log(f"    {n:4d}x  {b}")
    if alim_uygun_list:
        if open_n >= max_open:
            log("  Uygun ama slot yok (ilk 10):")
        else:
            log(f"  Uygun sinyaller ({open_n}/{max_open} slot dolu) — shadow acmiyorsa WS/fiyat/bug:")
        for sym, d, c in sorted(alim_uygun_list, key=lambda x: -x[2])[:10]:
            log(f"    {sym:14s} {d:5s} conf={c:.0%}")

    log(f"\n[5] SON 30 COIN ORNEK — KARAR ZINCIRI")
    sample_syms = symbols[-30:] if len(symbols) >= 30 else symbols
    for sym, _, _ in alim_uygun_list[:5]:
        if sym not in sample_syms:
            sample_syms.append(sym)
    extra_keys: list[str] = []
    for sym in sample_syms:
        for k in (
            f"agents:verdict:{sym}",
            f"learn:profile:{sym}",
            f"binance:ticker:{sym.lower()}",
            f"features:latest:{sym}",
            f"klines:1h:{sym}",
            f"trade:cooldown:shadow:{sym.upper()}",
        ):
            if k not in detail_raw:
                extra_keys.append(k)
    if extra_keys:
        detail_raw.update(mget_map(extra_keys, "ornek"))

    log(f"  {'SYMBOL':14s} {'SIG':5s} {'CONF':6s} {'AGENT':6s} {'AC':5s} {'LEARN':10s} {'GATE':22s} {'FIYAT':>8s}")
    log("  " + "-" * 78)
    for sym in sample_syms:
        sig = signals.get(sym)
        verdict = jparse(detail_raw.get(f"agents:verdict:{sym}")) or {}
        learn = jparse(detail_raw.get(f"learn:profile:{sym}")) or {}
        cd_raw = detail_raw.get(f"trade:cooldown:shadow:{sym.upper()}")
        cooled = bool(cd_raw and time.time() < float(cd_raw or 0))
        block = classify_shadow_block(sig, sym, cooled, open_n, max_open, rules)
        if sym in open_positions:
            block = f"ACIK_{open_positions[sym].get('direction', '?')}"
        price = ticker_price(
            detail_raw.get(f"binance:ticker:{sym.lower()}"),
            detail_raw.get(f"features:latest:{sym}"),
            detail_raw.get(f"klines:1h:{sym}"),
        )
        log(decision_row(sym, sig, verdict, learn, block, price))

    if near_miss:
        log(f"\n[5b] YAKIN KACANLAR (conf>=55%, reddedildi) — {len(near_miss)}")
        for sym, d, c, r in sorted(near_miss, key=lambda x: -x[2])[:12]:
            log(f"    {sym:14s} {d:5s} conf={c:.0%}  {r[:55]}")

    log("\n[6] SHADOW SLOT ANALIZI")
    pos_keys_raw = rc("KEYS", "shadow:positions:*")
    pos_keys = [k for k in pos_keys_raw.splitlines() if k and k != "(nil)"]
    shadow_pos_map: dict[str, dict] = {}
    if pos_keys:
        pos_raw = mget_map(pos_keys, "shadow-pos")
        log(f"  Redis shadow pozisyon key: {len(pos_keys)}")
        for pk in sorted(pos_keys)[:max_open]:
            pos = jparse(pos_raw.get(pk)) or {}
            sym = pos.get("symbol", pk.split(":")[-1])
            shadow_pos_map[sym] = pos
            sid = pk.split(":")[2] if pk.count(":") >= 2 else "?"
            opened = float(pos.get("time", pos.get("opened_at", pos.get("entry_time", 0))) or 0)
            hold = int(time.time() - opened) if opened else 0
            kalan = max(0, max_hold - hold)
            entry = float(pos.get("price", pos.get("entry_price", 0)) or 0)
            ladder = pos.get("ladder") or {}
            lev = float(ladder.get("leverage", risk_lim["max_leverage"]) or risk_lim["max_leverage"])
            size = float(pos.get("size_usd", 0) or 0)
            log(
                f"  {sid}/{sym}: {pos.get('direction','?')} hold={hold}s kalan_max={kalan}s "
                f"entry={entry:.4f} size=${size:.0f} lev={lev:.0f}x "
                f"sl={float(ladder.get('stop_loss_pct',0)):.1f}% "
                f"tp={float(ladder.get('take_profit_pct',0)):.1f}%"
            )
    else:
        log("  shadow:positions:* bos (portfolio uzerinden okunuyor)")

    log(f"\n[7] ACIK POZISYONLAR — DETAY ({len(portfolio.get('positions') or [])})")
    open_syms = [p.get("symbol") for p in (portfolio.get("positions") or []) if p.get("symbol")]
    open_extra: list[str] = []
    for sym in open_syms:
        for k in (
            f"agents:verdict:{sym}",
            f"context:latest:{sym}",
            f"learn:profile:{sym}",
            f"binance:ticker:{sym.lower()}",
            f"features:latest:{sym}",
            f"klines:1h:{sym}",
        ):
            if k not in detail_raw:
                open_extra.append(k)
    if open_extra:
        detail_raw.update(mget_map(open_extra, "acik"))

    for p in portfolio.get("positions") or []:
        sym = p.get("symbol", "?")
        sig = signals.get(sym) or {}
        verdict = jparse(detail_raw.get(f"agents:verdict:{sym}")) or {}
        learn = jparse(detail_raw.get(f"learn:profile:{sym}")) or {}
        ctx = jparse(detail_raw.get(f"context:latest:{sym}")) or {}
        feat = features.get(sym) or jparse(detail_raw.get(f"features:latest:{sym}")) or {}
        entry = float(p.get("entry_price", 0))
        opened = float(p.get("opened_at", p.get("entry_time", 0)) or 0)
        hold = int(time.time() - opened) if opened else int(p.get("hold_seconds", 0) or 0)
        price = ticker_price(
            detail_raw.get(f"binance:ticker:{sym.lower()}"),
            detail_raw.get(f"features:latest:{sym}"),
            detail_raw.get(f"klines:1h:{sym}"),
        )
        ladder = dict(p.get("ladder") or shadow_pos_map.get(sym, {}).get("ladder") or {})
        upnl = 0.0
        if entry > 0 and price > 0:
            upnl = (
                (price - entry) / entry * 100
                if p.get("direction") == "long"
                else (entry - price) / entry * 100
            )
        peak = float(p.get("peak_upnl_pct", p.get("peak_pnl_pct", ladder.get("peak_upnl_pct", 0))) or 0)
        kapanma = []
        if hold >= max_hold:
            kapanma.append(f"max_hold_asildi({hold}s)")
        elif max_hold - hold < 300:
            kapanma.append(f"max_hold_{max_hold - hold}s")
        if sig.get("direction") == "flat" and hold > int(rules.get("stale_verdict_sec", 1200)):
            kapanma.append("stale_flat_verdict")
        sl_pct = float(ladder.get("stop_loss_pct", 1.2) or 1.2)
        tp_pct = float(ladder.get("take_profit_pct", 1.5) or 1.5)
        if upnl <= -sl_pct:
            kapanma.append("hard_stop_yakin")
        if upnl >= tp_pct:
            kapanma.append("tp_yakin")
        log(f"  {sym} {p.get('direction')} [{p.get('source')}] "
            f"entry={entry:.4f} now={price:.4f} upnl={upnl:+.2f}% peak={peak:+.2f}% hold={hold}s")
        log(f"    sinyal={sig.get('direction','?')} conf={float(sig.get('confidence',0)):.0%} "
            f"valid={sig.get('is_valid', '?')}")
        log(f"    agent={verdict.get('direction','?')} conf={float(verdict.get('confidence',0)):.0%} "
            f"dissent={verdict.get('dissent_risk', '?')}")
        regime = ctx.get("regime", feat.get("regime", "?"))
        crisis = ctx.get("crisis_level", feat.get("crisis_level", "?"))
        log(f"    regime={regime} crisis={crisis}")
        if learn.get("avoid_hint"):
            log(f"    learn: {str(learn.get('avoid_hint'))[:70]}")
        if kapanma:
            log(f"    beklenen cikis: {', '.join(kapanma)}")

    log(f"\n[7b] KALDIRAC & AL/SAT DENETIMI — acik {len(portfolio.get('positions') or [])} pozisyon")
    log(
        "  Paper shadow: margin kilitlenir, notional = margin × coin_kaldıracı. "
        "Kaldıraç sinyal analizinden (ATR+crisis+conf+regime)."
    )
    log(
        f"  Formul: size = min(port*{risk_lim['max_position_pct']*100:.0f}%, slot*0.92) "
        f"* min(conf,85%) * min(lev/3,1)  |  acilis: BUY/SELL_SHORT, kapanis: SELL/BUY_COVER"
    )
    log(
        f"  {'SYMBOL':12s} {'KAYNAK':6s} {'ISLEM':10s} {'$SIZE':>7s} {'PORT%':>6s} "
        f"{'LEV':>4s} {'NOTION':>8s} {'SL%':>5s} {'TP%':>5s} {'RR':>4s} {'CONF':>5s} {'SONUC':8s}"
    )
    log("  " + "-" * 88)
    for p in portfolio.get("positions") or []:
        sym = p.get("symbol", "?")
        sig = signals.get(sym) or {}
        price = ticker_price(
            detail_raw.get(f"binance:ticker:{sym.lower()}"),
            detail_raw.get(f"features:latest:{sym}"),
            detail_raw.get(f"klines:1h:{sym}"),
        )
        opened = float(p.get("opened_at", p.get("entry_time", 0)) or 0)
        hold = int(time.time() - opened) if opened else 0
        ladder = dict(p.get("ladder") or shadow_pos_map.get(sym, {}).get("ladder") or {})
        audit = audit_position_decision(
            p, ladder, sig, rules, risk_lim, pv, price, hold, max_hold
        )
        log(
            f"  {sym:12s} {str(p.get('source','?'))[:6]:6s} {audit['side']:10s} "
            f"${audit['size']:6.0f} {audit['port_pct']*100:5.1f}% "
            f"{audit['leverage']:3.0f}x ${audit['notional']:7.0f} "
            f"{audit['sl']:4.1f} {audit['tp']:4.1f} {audit['rr']:3.2f} "
            f"{audit['entry_conf']:4.0%} {audit['verdict']:8s}"
        )
        log(f"    denetim: {', '.join(audit['checks'])}")
        if audit["risk_reasons"]:
            log(f"    risk: {', '.join(str(r) for r in audit['risk_reasons'][:3])}")
        if audit["kelly"] > 0:
            log(f"    kelly={audit['kelly']:.2%}")
        log(f"    cikis tetik: {', '.join(audit['exit_next'][:4])}")
        log(f"    kapanis tarafi: {audit['close_side']} (simdi upnl={audit['upnl']:+.2f}%)")

    if not (portfolio.get("positions") or []):
        exp_conf = 0.65
        exp_size = expected_shadow_size(
            pv, max_open, risk_lim["max_position_pct"], exp_conf,
            risk_lim["max_leverage"], open_n,
        )
        log("  Acik pozisyon yok — ornek yeni alim boyutu (conf=65%):")
        log(
            f"    ${exp_size:.0f} = {exp_size/pv*100:.1f}% portfoy, "
            f"notional~${exp_size * risk_lim['max_leverage']:.0f} @ "
            f"{risk_lim['max_leverage']:.0f}x"
        )

    log("\n[8] ISLEM GECMISI")
    raw_trades = rc("LRANGE", "oms:trade_history", "0", "499")
    all_trades: list[dict] = []
    for line in raw_trades.splitlines():
        try:
            all_trades.append(json.loads(line.strip()))
        except json.JSONDecodeError:
            pass
    all_trades.sort(key=lambda t: float(t.get("closed_at", 0)), reverse=True)

    log(f"\n[8a] SON 15 ISLEM — al/sat + boyut")
    log(
        f"  {'SYMBOL':12s} {'YON':5s} {'$SIZE':>7s} {'LEV':>4s} {'PNL':>8s} "
        f"{'$PNL':>9s} {'TUTMA':>7s} {'CIKIS':32s}"
    )
    log("  " + "-" * 88)
    for t in all_trades[:15]:
        sym = str(t.get("symbol", "?"))[:12]
        exit_r = str(t.get("exit_reason") or t.get("close_reason") or "?")[:32]
        ladder = t.get("ladder") or {}
        size = float(t.get("size_usd", 0) or 0)
        lev = float(ladder.get("leverage", risk_lim["max_leverage"]) or risk_lim["max_leverage"])
        log(
            f"  {sym:12s} {str(t.get('direction','?'))[:5]:5s} "
            f"${size:6.0f} {lev:3.0f}x "
            f"{pct(float(t.get('pnl_pct',0))):>8s} "
            f"${float(t.get('pnl_usdt',0)):+8.2f} "
            f"{int(float(t.get('hold_seconds',0))):6d}s  {exit_r}"
        )

    exit_ctr: Counter = Counter()
    hold_buckets: Counter = Counter()
    for t in all_trades:
        ex = str(t.get("exit_reason") or t.get("close_reason") or "").strip() or "(bos)"
        exit_ctr[ex[:50]] += 1
        h = int(float(t.get("hold_seconds", 0)))
        if h < 120:
            hold_buckets["<2dk"] += 1
        elif h < 600:
            hold_buckets["2-10dk"] += 1
        elif h < 3600:
            hold_buckets["10-60dk"] += 1
        else:
            hold_buckets[">60dk"] += 1

    log("\n[8b] CIKIS NEDENI DAGILIMI (top 10)")
    for reason, n in exit_ctr.most_common(10):
        log(f"    {n:4d}x  {reason}")
    log(f"  Tutma suresi: {dict(hold_buckets)}")

    chron: list[dict] = []
    if all_trades:
        chron = sorted(all_trades, key=lambda t: float(t.get("closed_at", 0)))
        recent = chron[-50:]
        old = chron[:-50]

        def wr(ts: list[dict]) -> float:
            return sum(1 for t in ts if float(t.get("pnl_pct", 0)) > 0) / len(ts) if ts else 0.0

        log(f"\n[9] KARLILIK ({len(chron)} islem)")
        log(f"  WR tumu:           {wr(chron)*100:.1f}%")
        log(f"  WR son 50:         {wr(recent)*100:.1f}%")
        if old:
            log(f"  WR eski:           {wr(old)*100:.1f}%")
        sym_pnl: dict[str, float] = defaultdict(float)
        sym_n: dict[str, int] = defaultdict(int)
        for t in chron:
            s = str(t.get("symbol", "?"))
            sym_pnl[s] += float(t.get("pnl_usdt", 0))
            sym_n[s] += 1
        ranked = sorted(sym_pnl.items(), key=lambda x: x[1])
        log("  En kotu 5:")
        for sym, pnl_u in ranked[:5]:
            log(f"    {sym:14s} ${pnl_u:+.2f} ({sym_n[sym]} islem)")
        log("  En iyi 5:")
        for sym, pnl_u in ranked[-5:][::-1]:
            log(f"    {sym:14s} ${pnl_u:+.2f} ({sym_n[sym]} islem)")
        empty_exit = sum(
            1 for t in chron
            if not str(t.get("exit_reason") or t.get("close_reason") or "").strip()
        )
        if empty_exit:
            log(f"  UYARI: {empty_exit}/{len(chron)} cikis nedeni bos (eski kayitlar)")
    else:
        empty_exit = 0

    if leaderboard:
        log("\n[9b] SHADOW LEADERBOARD")
        lb = leaderboard if isinstance(leaderboard, list) else leaderboard.get("leaderboard", [])
        for row in (lb or [])[:3]:
            if isinstance(row, dict):
                log(f"  {row.get('shadow_id','?')}: trades={row.get('trades',0)} "
                    f"WR={float(row.get('win_rate',0))*100:.0f}% "
                    f"Sharpe={row.get('sharpe', '?')}")

    ticker_zero = sum(
        1 for sym in sample_syms
        if ticker_price(
            detail_raw.get(f"binance:ticker:{sym.lower()}"),
            detail_raw.get(f"features:latest:{sym}"),
            detail_raw.get(f"klines:1h:{sym}"),
        ) <= 0
    )
    log(f"\n[10] VERI KALITESI")
    log(f"  Ornekte fiyat=0:   {ticker_zero}/{len(sample_syms)} (WS kopuksa features.close kullanilir)")
    log(f"  Feature eksik:     {no_feature}")
    log(f"  Sinyal eksik:      {no_signal}")

    log("\n[11] ONCELIKLI AKSIYONLAR (etki sirasi)")
    actions: list[str] = []
    if open_n >= max_open:
        actions.append(
            f"KRITIK: Shadow {open_n}/{max_open} dolu — yeni alim IMKANSIZ. "
            f"Acik: {', '.join(open_syms)}. Kapanis veya max_hold beklenmeli."
        )
    if len(alim_uygun_list) > 0 and open_n < max_open:
        actions.append(
            f"KRITIK: {len(alim_uygun_list)} ALIM_UYGUN ama sadece {open_n}/{max_open} acik — "
            f"sinyal VAR, shadow acmiyor (WS/fiyat veya kod hatasi). "
            f"En iyi: {alim_uygun_list[0][0]} {alim_uygun_list[0][2]:.0%}"
        )
    elif len(alim_uygun_list) > 0 and open_n >= max_open:
        actions.append(
            f"{len(alim_uygun_list)} ALIM_UYGUN sinyal var ama slot yok — "
            f"en iyi: {alim_uygun_list[0][0]} {alim_uygun_list[0][1]} {alim_uygun_list[0][2]:.0%}"
        )
    if valid_long or valid_short:
        actions.append(
            f"Pipeline OK: {len(valid_long)} long + {len(valid_short)} short gecerli sinyal uretiyor"
        )
    top_reject = reject_ctr.most_common(1)
    if top_reject and "flat" in top_reject[0][0].lower():
        actions.append(
            f"Sinyallerin cogu flat ({top_reject[0][1]}x) — agent ensemble temkinli, normal"
        )
    if near_miss:
        actions.append(
            f"{len(near_miss)} yakin kacan (conf 55-58%) — paper min conf "
            f"{float(rules.get('paper_min_conf',0.57))*100:.0f}% esigi"
        )
    if empty_exit > len(all_trades) * 0.3 and all_trades:
        actions.append(f"Eski {empty_exit} islemde exit_reason bos — yeni islemlerde duzeldi mi kontrol")
    if chron:
        wr_recent = sum(1 for t in chron[-50:] if float(t.get("pnl_pct", 0)) > 0)
        if wr_recent >= 25:
            actions.append(f"Son 50 WR iyilesiyor ({wr_recent}/50 kazanc) — kurallar etkili olabilir")
    bad_in_universe = [s for s in symbols if s in set(rules.get("blacklist") or [])]
    if bad_in_universe:
        actions.append(f"Blacklist'te ama evrende: {len(bad_in_universe)} sembol")
    if not actions:
        actions.append("Ozel sorun yok — paper devam, slot acilinca alim beklenir")
    for i, a in enumerate(actions, 1):
        log(f"  {i}. {a}")

    elapsed = time.time() - t0
    log(f"\n  Sure: {elapsed:.1f} sn")
    log("=" * 72)


if __name__ == "__main__":
    main()
