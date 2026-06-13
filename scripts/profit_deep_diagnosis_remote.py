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
            "min_agent_align_conf": pr.MIN_AGENT_ALIGN_CONF,
            "slot_rotate_min_conf": pr.SLOT_ROTATE_MIN_CONF,
            "min_rr_ratio": pr.MIN_RR_RATIO,
            "shadow_max_open": pr.SHADOW_MAX_OPEN,
            "shadow_hard_stop_pct": pr.SHADOW_HARD_STOP_PCT,
            "max_hold_sec": pr.MAX_POSITION_HOLD_SEC,
            "stale_verdict_sec": pr.STALE_VERDICT_HOLD_SEC,
            "cooldown_sec": pr.PAPER_SYMBOL_COOLDOWN_SEC,
            "loss_cooldown_sec": pr.LOSS_COOLDOWN_SEC,
            "symbol_cooldown_sec": pr.SYMBOL_COOLDOWN_SEC,
            "breakeven_activate_pct": pr.BREAKEVEN_ACTIVATE_PCT,
            "breakeven_floor_pct": pr.BREAKEVEN_FLOOR_PCT,
            "guard_tp_pct": pr.GUARD_TAKE_PROFIT_PCT,
            "guard_max_loss_pct": pr.GUARD_MAX_LOSS_PCT,
            "default_stop_pct": pr.DEFAULT_STOP_LOSS_PCT,
            "default_tp_tiers": pr.profit_tiers(),
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
    raw_pos = float(risk.get("max_position_pct", 0.05) or 0.05)
    try:
        sys.path.insert(0, str(ROOT / "services" / "shared"))
        from risk_limits import normalize_max_position_pct  # noqa: WPS433

        max_pos = normalize_max_position_pct(raw_pos)
    except Exception:
        max_pos = raw_pos / 100.0 if raw_pos > 1 else raw_pos
        max_pos = max(0.001, min(max_pos, 1.0))
    return {
        "max_leverage": min(max_lev, 3.0),
        "max_position_pct": max_pos,
        "max_open_positions": int(risk.get("max_open_positions", 30) or 30),
    }


def portfolio_value_usd(portfolio: dict, cap_raw: dict | None = None) -> float:
    if cap_raw:
        v = float(cap_raw.get("usd_cap") or cap_raw.get("portfolio_usd") or cap_raw.get("usd_capital") or 0)
        if v > 0:
            return v
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


def infer_shadow_equity(
    portfolio: dict,
    meta_raw: dict,
    max_open: int,
    cap_raw: dict | None = None,
) -> tuple[float, float, str]:
    """(configured_cap, live_equity, kaynak) — boyutlandirma canli equity ile yapilir."""
    configured = portfolio_value_usd(portfolio, cap_raw)
    live_raw = jparse(meta_raw.get("portfolio:live_equity:v1"))
    if live_raw:
        live = float(
            live_raw.get("live_equity_usd")
            or live_raw.get("equity_usd")
            or live_raw.get("equity")
            or 0
        )
        if live > 0:
            return configured, live, "redis:live_equity"

    slot_inferred: list[float] = []
    for pos in portfolio.get("positions") or []:
        if str(pos.get("source", "")).lower() != "shadow":
            continue
        ladder = pos.get("ladder") or {}
        sb = float(ladder.get("slot_budget_usd", 0) or 0)
        if sb > 0 and max_open > 0:
            slot_inferred.append(sb * max_open)
    if slot_inferred:
        live = sum(slot_inferred) / len(slot_inferred)
        return configured, live, "ladder:slot_budget"

    eq = float(portfolio.get("equity", portfolio.get("current_equity", 0)) or 0)
    if eq > 0:
        return configured, eq, "portfolio:state"
    return configured, configured, "configured_default"


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
    size = base_usd * min(confidence, 0.85)
    if open_n >= max_open * 0.8:
        size *= 0.85
    return size


def read_env_flags() -> dict:
    env_path = Path(".env")
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    keys = (
        "DRY_RUN", "PORTFOLIO_VALUE", "SHADOW_OPEN_IDS", "SHADOW_ONE_PER_SYMBOL",
        "SHADOW_MIN_CONFIDENCE", "PAPER_MIN_SIGNAL_CONFIDENCE", "TRADING_SYMBOLS",
        "TRADE_FEE_PCT_PER_SIDE", "BINANCE_TESTNET",
    )
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k in keys:
            out[k] = v.strip().strip('"').strip("'")
    return out


def shadow_counts_from_keys(pos_keys: list[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for pk in pos_keys:
        parts = pk.split(":")
        if len(parts) >= 3:
            counts[parts[2]] += 1
    return dict(counts)


def shadow_owner_from_keys(pos_keys: list[str], sym: str) -> str | None:
    for pk in pos_keys:
        parts = pk.split(":")
        if len(parts) >= 4 and parts[3] == sym:
            return parts[2]
    return None


def signal_decision_fields(sig: dict | None) -> dict:
    if not sig:
        return {}
    dec = sig.get("decision") or {}
    sl = float(dec.get("stop_loss_pct") or sig.get("stop_loss_pct") or 0)
    tp_list = dec.get("take_profit_tiers_pct") or sig.get("take_profit_tiers") or []
    tp = float(tp_list[0] if tp_list else 0)
    risk = sig.get("risk") or {}
    return {
        "direction": str(sig.get("direction", "flat")),
        "confidence": float(sig.get("confidence", 0)),
        "is_valid": bool(sig.get("is_valid")),
        "reject_reason": str(sig.get("reject_reason") or ""),
        "leverage": float(sig.get("leverage") or risk.get("recommended_leverage") or 0),
        "leverage_reasons": sig.get("leverage_reasons") or risk.get("leverage_reasons") or [],
        "stop_loss_pct": sl,
        "take_profit_pct": tp,
        "rr": (tp / sl) if sl > 0 and tp > 0 else 0,
        "kelly_fraction": float(sig.get("kelly_fraction", 0) or 0),
        "trade_action": str(sig.get("trade_action") or ""),
        "consensus_reasoning": str(sig.get("consensus_reasoning") or sig.get("reasoning") or "")[:200],
        "regime": str(sig.get("regime") or ""),
        "crisis_level": int(sig.get("crisis_level", 0) or 0),
    }


def trace_shadow_entry(
    sym: str,
    sig: dict | None,
    verdict: dict | None,
    ctx: dict | None,
    price: float,
    cooled: bool,
    halted: bool,
    rules: dict,
    open_positions: dict,
    shadow_counts: dict[str, int],
    shadow_owner: str | None,
    pv: float,
    risk_lim: dict,
) -> list[str]:
    """simulate_tick ile ayni sira — neden acmadi/acar."""
    steps: list[str] = []
    try:
        sys.path.insert(0, str(ROOT / "services" / "shared"))
        from profit_rules import (  # noqa: WPS433
            agent_entry_ok,
            entry_allowed,
            is_blacklisted,
        )
    except Exception as exc:
        steps.append(f"HATA profit_rules: {exc}")
        return steps

    if halted:
        steps.append("1.BLOCK trading_halted=True")
        return steps
    steps.append("1.PASS trading_halted=False")

    if is_blacklisted(sym):
        steps.append("2.BLOCK blacklist")
        return steps
    steps.append("2.PASS blacklist yok")

    if cooled:
        steps.append("3.BLOCK cooldown_aktif")
        return steps
    steps.append("3.PASS cooldown yok")

    if not sig:
        steps.append("4.BLOCK sinyal_yok")
        return steps
    d = str(sig.get("direction", "flat"))
    conf = float(sig.get("confidence", 0))
    valid = bool(sig.get("is_valid"))
    if d == "flat" or not valid:
        rr = str(sig.get("reject_reason") or "gecersiz")[:60]
        steps.append(f"4.BLOCK direction={d} valid={valid} reason={rr}")
        return steps
    steps.append(f"4.PASS signal {d} conf={conf:.0%} valid=True")

    ok_agent, agent_why = agent_entry_ok(d, verdict, conf)
    v_dir = str((verdict or {}).get("direction", "?"))
    v_conf = float((verdict or {}).get("confidence", 0))
    if not ok_agent:
        steps.append(f"5.BLOCK agent: {agent_why} (verdict={v_dir} {v_conf:.0%})")
        return steps
    steps.append(f"5.PASS agent: {agent_why} (verdict={v_dir} {v_conf:.0%})")

    crisis = int((ctx or {}).get("crisis_level", 0) or 0)
    if crisis >= 2 and conf < 0.65:
        steps.append(f"6.BLOCK crisis_level={crisis} conf={conf:.0%} < 65%")
        return steps
    steps.append(f"6.PASS crisis_level={crisis}")

    if price <= 0:
        steps.append("7.BLOCK fiyat=0 (WS/features/klines yok — shadow acamaz)")
        return steps
    steps.append(f"7.PASS fiyat={price:.6f}")

    dec = sig.get("decision") or {}
    sl = float(dec.get("stop_loss_pct") or sig.get("stop_loss_pct") or 1.2)
    tp_list = dec.get("take_profit_tiers_pct") or sig.get("take_profit_tiers") or [1.5]
    tp = float(tp_list[0] if tp_list else 1.5)
    ok_ent, ent_why = entry_allowed(conf, stop_pct=sl, tp_pct=tp)
    if not ok_ent:
        steps.append(f"8.BLOCK entry_allowed: {ent_why} sl={sl}% tp={tp}% rr={tp/sl:.2f}")
        return steps
    steps.append(f"8.PASS entry_allowed sl={sl}% tp={tp}% rr={tp/sl:.2f}")

    max_open = int(rules.get("shadow_max_open", 30))
    max_pos = float(risk_lim.get("max_position_pct", 0.05))
    try:
        from risk_limits import normalize_max_position_pct  # noqa: WPS433

        max_pos = normalize_max_position_pct(max_pos)
    except Exception:
        if max_pos > 1:
            max_pos = max_pos / 100.0
    lev = float(sig.get("leverage") or (sig.get("risk") or {}).get("recommended_leverage") or 1)
    lev = max(1.0, min(lev, float(risk_lim.get("max_leverage", 3))))
    leader = (read_env_flags().get("SHADOW_OPEN_IDS") or "SHADOW_A").split(",")[0].strip()
    open_n = int(shadow_counts.get(leader, 0))
    slot_budget = pv / max(max_open, 1)
    base_usd = min(pv * max_pos, slot_budget * 0.92)
    margin = base_usd * min(conf, 0.85)
    if open_n >= max_open * 0.8:
        margin *= 0.85
    notional = margin * lev
    steps.append(
        f"9.SIZE pv=${pv:,.0f} slot=${slot_budget:.0f} margin=${margin:.0f} "
        f"lev={lev:.0f}x notional=${notional:.0f} open={open_n}/{max_open}"
    )
    if margin <= 0:
        steps.append("9.BLOCK margin<=0")
        return steps

    one_per = (read_env_flags().get("SHADOW_ONE_PER_SYMBOL", "true").lower()
               in ("1", "true", "yes"))
    if one_per and shadow_owner and shadow_owner != leader:
        steps.append(f"10.BLOCK SHADOW_ONE_PER_SYMBOL owner={shadow_owner} (baska shadow tutuyor)")
        return steps
    if one_per and shadow_owner:
        steps.append(f"10.PASS owner={shadow_owner} zaten acik")
        return steps
    steps.append("10.PASS sembol baska shadow'da yok")

    if sym in open_positions:
        steps.append(f"11.SKIP zaten_acik portfolio={open_positions[sym].get('direction')}")
        return steps

    if open_n >= max_open:
        steps.append(
            f"12.BLOCK slot_dolu {leader}={open_n}/{max_open} "
            f"(rotate icin conf>={float(rules.get('slot_rotate_min_conf', 0.68)):.0%})"
        )
        return steps
    steps.append(f"12.OPEN_HAZIR {leader} BUY/SELL_SHORT margin=${margin:.0f} @ {price:.6f}")
    return steps


def log_signal_full(sym: str, sig: dict | None, verdict: dict | None, ctx: dict | None,
                    feat: dict | None, price: float, learn: dict | None) -> None:
    sf = signal_decision_fields(sig)
    regime = str((ctx or {}).get("regime") or sf.get("regime") or (feat or {}).get("regime") or "?")
    crisis = (ctx or {}).get("crisis_level", sf.get("crisis_level", "?"))
    log(f"  --- {sym} ---")
    log(f"    sinyal: yon={sf.get('direction')} conf={sf.get('confidence',0):.0%} "
        f"valid={sf.get('is_valid')} action={sf.get('trade_action') or '-'}")
    if sf.get("reject_reason"):
        log(f"    red: {sf['reject_reason']}")
    log(f"    risk: lev={sf.get('leverage',0):.0f}x rr={sf.get('rr',0):.2f} "
        f"sl={sf.get('stop_loss_pct',0):.1f}% tp={sf.get('take_profit_pct',0):.1f}% "
        f"kelly={sf.get('kelly_fraction',0):.2%}")
    reasons = sf.get("leverage_reasons") or []
    if reasons:
        log(f"    lev_neden: {', '.join(str(r) for r in reasons[:6])}")
    if sf.get("consensus_reasoning"):
        log(f"    gerekce: {sf['consensus_reasoning'][:160]}")
    if verdict:
        log(f"    agent: yon={verdict.get('direction','?')} conf={float(verdict.get('confidence',0)):.0%} "
            f"dissent={verdict.get('dissent_risk','?')}")
        if verdict.get("consensus_reasoning"):
            log(f"    agent_ozet: {str(verdict.get('consensus_reasoning'))[:120]}")
    log(f"    context: regime={regime} crisis={crisis}")
    if learn:
        for k in ("avoid_hint", "regime", "win_rate", "avg_pnl_pct", "trades"):
            if learn.get(k) is not None:
                log(f"    learn.{k}: {learn.get(k)}")
    atr = float((feat or {}).get("atr_pct", 0) or 0)
    if atr:
        log(f"    feature: atr_pct={atr:.4f} close={float((feat or {}).get('close',0) or 0):.6f}")
    log(f"    fiyat: {price:.6f}" if price > 0 else "    fiyat: 0 (WS kopuk)")


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


def log_ozet_panel(
    *,
    rules: dict,
    risk_lim: dict,
    max_open: int,
    open_n: int,
    symbols: list[str],
    signals: dict,
    features: dict,
    alim_uygun_list: list[tuple[str, str, float]],
    block_all: Counter,
    open_positions: dict[str, dict],
    portfolio: dict,
    cd_map: dict[str, str | None],
    all_trades: list[dict],
    chron: list[dict],
    detail_raw: dict,
    feat_raw_map: dict,
    valid_long: list,
    valid_short: list,
    directional: list,
) -> None:
    """Tek bakista: sinir, tarama, acik, bekleyen, alinan, zarar."""
    log("\n" + "=" * 72)
    log("  OZET PANEL — sinir / tarama / acik / bekleyen / alim / zarar")
    log("=" * 72)

    log("\n  [SINIRLAR — kac tane alabilir?]")
    log(f"    Shadow max acik:     {max_open} pozisyon (slot)")
    log(f"    Immunity max acik:   {risk_lim['max_open_positions']} pozisyon")
    log(f"    Islem basi max:      portfoyun %{risk_lim['max_position_pct']*100:.1f}'i")
    log(f"    Max kaldirac:        {risk_lim['max_leverage']:.0f}x")
    log(f"    Sembol basi:         1 pozisyon (SHADOW_ONE_PER_SYMBOL)")
    log(f"    Blacklist:           {len(rules.get('blacklist') or [])} coin engelli")
    log(f"    Min shadow conf:     {float(rules.get('shadow_min_conf', 0.60))*100:.0f}%")
    log(f"    Cooldown:            {int(rules.get('cooldown_sec', 600))}s "
        f"(zarar sonrasi {int(rules.get('loss_cooldown_sec', 1800))}s)")

    total_open = int(portfolio.get("total_open", 0) or 0)
    oms_open = int(portfolio.get("oms_open", 0) or 0)
    bos_slot = max(0, max_open - open_n)
    log(f"\n  [ANLIK — simdi kac tane acik?]")
    log(f"    Acik toplam:         {total_open} (shadow={open_n}, oms={oms_open})")
    log(f"    Dolu slot:           {open_n}/{max_open}  |  Bos slot: {bos_slot}")
    if open_n >= max_open:
        log("    !! SLOT DOLU — yeni alim yapilamaz, once kapanis gerekir")

    log(f"\n  [TARAMA — alim komutu icin evren]")
    log(f"    Taranan sembol:      {len(symbols)}")
    log(f"    Feature var:         {len(features)}/{len(symbols)}")
    log(f"    Sinyal var:          {len(signals)}/{len(symbols)}")
    log(f"    Yonlu sinyal:        {len(directional)} (long+short)")
    log(f"    Gecerli LONG:        {len(valid_long)}")
    log(f"    Gecerli SHORT:       {len(valid_short)}")
    log(f"    ALIM_UYGUN:          {len(alim_uygun_list)} sembol (tum kontrolleri gecti)")
    log("    Blokaj (top 8):")
    for b, n in block_all.most_common(8):
        log(f"      {n:4d}x  {b}")

    bekleyen_hazir: list[tuple[str, str, float]] = []
    bekleyen_cooldown: list[str] = []
    bekleyen_slot_yok: list[tuple[str, str, float]] = []
    for sym, d, c in alim_uygun_list:
        if sym in open_positions:
            continue
        cd_raw = cd_map.get(f"trade:cooldown:shadow:{sym.upper()}")
        cooled = bool(cd_raw and time.time() < float(cd_raw or 0))
        if cooled:
            bekleyen_cooldown.append(sym)
        elif open_n >= max_open:
            bekleyen_slot_yok.append((sym, d, c))
        else:
            bekleyen_hazir.append((sym, d, c))

    log(f"\n  [BEKLEYEN — alinmayi bekleyen]")
    log(f"    Hazir (slot var):    {len(bekleyen_hazir)} sembol — shadow tick ile acilir")
    for sym, d, c in sorted(bekleyen_hazir, key=lambda x: -x[2])[:8]:
        log(f"      -> {sym:14s} {d:5s} conf={c:.0%}")
    if len(bekleyen_hazir) > 8:
        log(f"      ... +{len(bekleyen_hazir) - 8} daha")
    log(f"    Cooldown'da:         {len(bekleyen_cooldown)} sembol")
    if bekleyen_cooldown[:5]:
        log(f"      -> {', '.join(bekleyen_cooldown[:5])}")
    log(f"    Slot dolu yuzunden:  {len(bekleyen_slot_yok)} sembol (sinyal OK, yer yok)")
    if bekleyen_slot_yok[:3]:
        for sym, d, c in bekleyen_slot_yok[:3]:
            log(f"      -> {sym:14s} {d:5s} conf={c:.0%}")

    positions = portfolio.get("positions") or []
    log(f"\n  [ACIK POZISYONLAR — su an tutulan] ({len(positions)})")
    if not positions:
        log("    (acik pozisyon yok)")
    for p in positions:
        sym = p.get("symbol", "?")
        entry = float(p.get("entry_price", 0) or 0)
        price = ticker_price(
            detail_raw.get(f"binance:ticker:{sym.lower()}"),
            feat_raw_map.get(f"features:latest:{sym}"),
            detail_raw.get(f"klines:1h:{sym}"),
        )
        upnl = 0.0
        if entry > 0 and price > 0:
            upnl = (
                (price - entry) / entry * 100
                if p.get("direction") == "long"
                else (entry - price) / entry * 100
            )
        log(
            f"    {sym:14s} {str(p.get('direction','?')):5s} "
            f"entry={entry:.4f} upnl={upnl:+.2f}% "
            f"size=${float(p.get('size_usd',0) or 0):.0f} "
            f"[{p.get('source','?')}]"
        )

    log(f"\n  [ALINMIS — islem gecmisi] ({len(all_trades)} kayit)")
    if not all_trades:
        log("    Henuz kapanmis islem yok")
    else:
        wins = sum(1 for t in all_trades if float(t.get("pnl_pct", 0)) > 0)
        losses = sum(1 for t in all_trades if float(t.get("pnl_pct", 0)) < 0)
        flat = len(all_trades) - wins - losses
        total_pnl = sum(float(t.get("pnl_usdt", 0)) for t in all_trades)
        log(f"    Toplam islem:        {len(all_trades)}")
        log(f"    Kazanc / Zarar:      {wins} / {losses} (flat={flat})")
        wr_pct = wins / len(all_trades) * 100 if all_trades else 0
        log(f"    Win rate:            {wr_pct:.1f}%")
        log(f"    Toplam PnL:          ${total_pnl:+,.2f}")
        log("    Son 5 alinan/kapanan:")
        for t in all_trades[:5]:
            sym = str(t.get("symbol", "?"))
            pnl_u = float(t.get("pnl_usdt", 0))
            pnl_p = float(t.get("pnl_pct", 0))
            mark = "WIN" if pnl_p > 0 else ("LOSS" if pnl_p < 0 else "FLAT")
            log(
                f"      {sym:14s} {str(t.get('direction','?')):5s} "
                f"{pct(pnl_p)} ${pnl_u:+.2f} [{mark}] "
                f"{str(t.get('exit_reason') or t.get('close_reason') or '?')[:28]}"
            )

    log(f"\n  [ZARAR — en cok kaybettiren]")
    if chron:
        sym_pnl: dict[str, float] = defaultdict(float)
        sym_n: dict[str, int] = defaultdict(int)
        for t in chron:
            s = str(t.get("symbol", "?"))
            sym_pnl[s] += float(t.get("pnl_usdt", 0))
            sym_n[s] += 1
        losers = [(s, p) for s, p in sym_pnl.items() if p < 0]
        losers.sort(key=lambda x: x[1])
        if losers:
            for sym, pnl_u in losers[:8]:
                log(f"    {sym:14s} ${pnl_u:+.2f} ({sym_n[sym]} islem)")
        else:
            log("    Zarar eden sembol yok (tum islemler >= 0)")
        winners = [(s, p) for s, p in sym_pnl.items() if p > 0]
        winners.sort(key=lambda x: -x[1])
        if winners:
            log("  [KAZANC — en iyi semboller]")
            for sym, pnl_u in winners[:5]:
                log(f"    {sym:14s} ${pnl_u:+.2f} ({sym_n[sym]} islem)")
    else:
        log("    Islem gecmisi bos")

    log("=" * 72)


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
        try:
            load_part = uptime.split("load average:")[-1].strip().split(",")[0].strip()
            load_1 = float(load_part)
            if load_1 > 15:
                log(f"  !! UYARI: VPS yuksek yuk (load {load_1:.0f}) — [5]+ bolumler yavas; OZET [4z] erken gelir")
        except (IndexError, ValueError):
            pass
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
        "portfolio:capital:v1",
        "portfolio:try:v1",
        "portfolio:live_equity:v1",
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
    cap_raw = jparse(meta_raw.get("portfolio:capital:v1")) or jparse(meta_raw.get("portfolio:try:v1"))
    configured_cap, live_eq, eq_source = infer_shadow_equity(portfolio, meta_raw, max_open, cap_raw)
    pv = configured_cap

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
    env_flags = read_env_flags()
    log(f"  Paper min conf:    {float(rules.get('paper_min_conf', 0.57))*100:.0f}%")
    log(f"  Shadow min conf:   {float(rules.get('shadow_min_conf', 0.60))*100:.0f}%")
    log(f"  OMS min conf:      {float(rules.get('oms_min_conf', 0.58))*100:.0f}%")
    log(f"  Agent align min:   {float(rules.get('min_agent_align_conf', 0.38))*100:.0f}%")
    log(f"  Slot rotate min:   {float(rules.get('slot_rotate_min_conf', 0.68))*100:.0f}%")
    log(f"  Min R:R:           {float(rules.get('min_rr_ratio', 1.25)):.2f}")
    log(f"  Shadow max open:   {max_open}")
    log(f"  Max tutma:         {max_hold}s ({max_hold//60} dk)")
    log(f"  Stale verdict:     {rules.get('stale_verdict_sec', 1200)}s")
    log(f"  Cooldown:          {rules.get('cooldown_sec', 600)}s (zarar: {rules.get('loss_cooldown_sec', 1800)}s)")
    log(f"  Breakeven:         +{float(rules.get('breakeven_activate_pct', 0.35)):.2f}% → floor {float(rules.get('breakeven_floor_pct', 0.08)):.2f}%")
    log(f"  Hard stop:         {float(rules.get('shadow_hard_stop_pct', 1.2)):.1f}%")
    log(f"  Default SL/TP:     {float(rules.get('default_stop_pct', 1.2)):.1f}% / {rules.get('default_tp_tiers', [1.5])}")
    if rules.get("blacklist"):
        log(f"  Blacklist:         {', '.join(rules['blacklist'])}")
    log(f"  Max leverage:      {risk_lim['max_leverage']:.0f}x (immunity cap 3x)")
    log(f"  Max pozisyon:      {risk_lim['max_position_pct']*100:.1f}% portfoy / islem")
    cap_raw = jparse(meta_raw.get("portfolio:capital:v1")) or jparse(meta_raw.get("portfolio:try:v1"))
    if cap_raw:
        log(f"  Kasa (Redis):      usd_cap=${float(cap_raw.get('usd_cap', cap_raw.get('portfolio_usd', 0)) or 0):,.0f} "
            f"try={cap_raw.get('try_amount', '?')} kur={cap_raw.get('usd_try_rate', '?')}")
    log(f"  Portfoy baz:       ${configured_cap:,.0f} (dashboard/env)")
    log(f"  Canli equity:      ${live_eq:,.0f} ({eq_source})")
    if live_eq < configured_cap * 0.5:
        log(f"  !! UYARI: Canli equity yapilandirilan kasanin %{live_eq/configured_cap*100:.0f}'i — "
            f"islem boyutu ${live_eq/max(max_open,1):.0f}/slot (beklenen ${configured_cap/max(max_open,1):.0f})")
    log(f"  Slot butcesi:      ${live_eq / max(max_open, 1):,.0f} (canli/{max_open})")
    log(f"  DRY_RUN:           {env_flags.get('DRY_RUN', '?')}")
    log(f"  Shadow IDs:        {env_flags.get('SHADOW_OPEN_IDS', 'SHADOW_A')}")
    log(f"  One per symbol:    {env_flags.get('SHADOW_ONE_PER_SYMBOL', 'true')}")
    log(f"  Fee/side:          {env_flags.get('TRADE_FEE_PCT_PER_SIDE', '0.001')}")
    log(f"  Trading halted:    {halted.get('halted', False)}")
    if halted.get("reason"):
        log(f"  Halt nedeni:       {halted.get('reason')}")
    log(f"  WS:                {ws_status.get('status', '?')} "
        f"({ws_status.get('symbols', '?')} sembol)")
    if deploy:
        log(f"  Son deploy:        {deploy.get('deployed_at_iso', '?')} "
            f"v{deploy.get('version', '?')[:24]} sha={str(deploy.get('git_sha', '?'))[:12]}")
    open_n = int(portfolio.get("shadow_open", 0) or 0)
    log(f"  Acik pozisyon:     {portfolio.get('total_open', 0)} "
        f"(oms={portfolio.get('oms_open', 0)} shadow={open_n})")
    eq = float(portfolio.get("equity", portfolio.get("current_equity", 0)) or 0)
    pnl = float(portfolio.get("total_pnl", portfolio.get("daily_pnl", 0)) or 0)
    if eq:
        log(f"  Equity:            ${eq:,.2f}  gunluk PnL=${pnl:+,.2f}")
    log(f"  Evren:             long={uni_counts.get('long',0)} short={uni_counts.get('short',0)} "
        f"flat={uni_counts.get('flat',0)}")
    if sig_stats:
        log(f"  Signal engine:     processed={sig_stats.get('processed', '?')} "
            f"suppressed={sig_stats.get('suppressed_flat', '?')} "
            f"last_cycle={sig_stats.get('last_cycle_ts', '?')}")
    if guard_status:
        log(f"  Guard:             active={guard_status.get('active', '?')} "
            f"positions_watched={guard_status.get('positions', '?')}")

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
    regime_ctr: Counter = Counter()
    crisis_ctr: Counter = Counter()
    valid_long: list[tuple[str, float]] = []
    valid_short: list[tuple[str, float]] = []
    directional: list[tuple[str, str, float, bool]] = []
    near_miss: list[tuple] = []
    no_feature = no_signal = 0

    ctx_keys = [f"context:latest:{s}" for s in symbols]
    ctx_raw_map = mget_map(ctx_keys, "context")

    for sym in symbols:
        feat = jparse(feat_raw_map.get(f"features:latest:{sym}"))
        if feat:
            features[sym] = feat
        else:
            no_feature += 1
        ctx = jparse(ctx_raw_map.get(f"context:latest:{sym}")) or {}
        regime = str(ctx.get("regime") or feat.get("regime") if feat else "unknown")
        regime_ctr[regime[:20]] += 1
        crisis_ctr[str(ctx.get("crisis_level", feat.get("crisis_level", 0) if feat else 0))] += 1
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
        if d in ("long", "short"):
            directional.append((sym, d, conf, bool(sig.get("is_valid"))))
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
    log(f"  regime (top 6):    {dict(regime_ctr.most_common(6))}")
    log(f"  crisis dagilimi:   {dict(crisis_ctr)}")
    log(f"  yonlu sinyal:      {len(directional)} (long/short, valid+invalid)")
    log("  red (top 12):")
    for reason, n in reject_ctr.most_common(12):
        log(f"    {n:4d}x  {reason}")

    log("\n[3] GECERLI SINYALLER — OZET TABLO")
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

    log("\n[3b] GECERLI SINYALLER — TAM DETAY (LLM icin)")
    all_valid = [(s, c, "long") for s, c in valid_long] + [(s, c, "short") for s, c in valid_short]
    for sym, conf, _ in sorted(all_valid, key=lambda x: -x[1]):
        sig = signals.get(sym)
        verdict = jparse(detail_raw.get(f"agents:verdict:{sym}")) or {}
        ctx = jparse(ctx_raw_map.get(f"context:latest:{sym}")) or {}
        feat = features.get(sym)
        learn = jparse(detail_raw.get(f"learn:profile:{sym}")) or {}
        price = ticker_price(
            detail_raw.get(f"binance:ticker:{sym.lower()}"),
            feat_raw_map.get(f"features:latest:{sym}"),
            None,
        )
        log_signal_full(sym, sig, verdict, ctx, feat, price, learn)

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
            log(f"  Uygun sinyaller ({open_n}/{max_open} slot dolu) — shadow acmiyorsa asagidaki iz:")
        for sym, d, c in sorted(alim_uygun_list, key=lambda x: -x[2])[:10]:
            log(f"    {sym:14s} {d:5s} conf={c:.0%}")

    pos_keys_raw_early = rc("KEYS", "shadow:positions:*")
    pos_keys_early = [k for k in pos_keys_raw_early.splitlines() if k and k != "(nil)"]
    shadow_counts_early = shadow_counts_from_keys(pos_keys_early)

    log("\n[4b] SHADOW GIRIS IZI — ALIM_UYGUN adim adim (simulate_tick)")
    halted_flag = bool(halted.get("halted", False))
    for sym, d, c in sorted(alim_uygun_list, key=lambda x: -x[2])[:8]:
        sig = signals.get(sym)
        verdict = jparse(detail_raw.get(f"agents:verdict:{sym}")) or {}
        ctx = jparse(ctx_raw_map.get(f"context:latest:{sym}")) or {}
        cd_raw = cd_map.get(f"trade:cooldown:shadow:{sym.upper()}")
        cooled = bool(cd_raw and time.time() < float(cd_raw or 0))
        price = ticker_price(
            detail_raw.get(f"binance:ticker:{sym.lower()}"),
            feat_raw_map.get(f"features:latest:{sym}"),
            None,
        )
        owner = shadow_owner_from_keys(pos_keys_early, sym)
        steps = trace_shadow_entry(
            sym, sig, verdict, ctx, price, cooled, halted_flag, rules,
            open_positions, shadow_counts_early, owner, live_eq, risk_lim,
        )
        log(f"  {sym} ({d} conf={c:.0%}):")
        for st in steps:
            log(f"    {st}")

    log("\n[4c] YONLU AMA GECERSIZ — neden alinmadi")
    invalid_dir = [(s, d, c, v) for s, d, c, v in directional if not v]
    for sym, d, conf, _ in sorted(invalid_dir, key=lambda x: -x[2])[:15]:
        sig = signals.get(sym) or {}
        log(f"  {sym:14s} {d:5s} conf={conf:.0%}  red={str(sig.get('reject_reason','?'))[:55]}")

    # Islem gecmisi + acik pozisyon fiyatlari (OZET icin erken yukle)
    ozet_extra: list[str] = []
    for sym in (p.get("symbol") for p in (portfolio.get("positions") or []) if p.get("symbol")):
        for k in (
            f"binance:ticker:{sym.lower()}",
            f"features:latest:{sym}",
            f"klines:1h:{sym}",
        ):
            if k not in detail_raw:
                ozet_extra.append(k)
    if ozet_extra:
        detail_raw.update(mget_map(ozet_extra, "ozet-acik"))

    all_trades: list[dict] = []
    raw_trades = rc("LRANGE", "oms:trade_history", "0", "499")
    for line in raw_trades.splitlines():
        try:
            all_trades.append(json.loads(line.strip()))
        except json.JSONDecodeError:
            pass
    all_trades.sort(key=lambda t: float(t.get("closed_at", 0)), reverse=True)
    chron: list[dict] = (
        sorted(all_trades, key=lambda t: float(t.get("closed_at", 0))) if all_trades else []
    )

    log("\n[4z] OZET PANEL — sinir / tarama / acik / bekleyen / alim / zarar")
    log("  (Detay bolumler [5]+ asagida; VPS yuksek yukte uzun surebilir)")
    log_ozet_panel(
        rules=rules,
        risk_lim=risk_lim,
        max_open=max_open,
        open_n=open_n,
        symbols=symbols,
        signals=signals,
        features=features,
        alim_uygun_list=alim_uygun_list,
        block_all=block_all,
        open_positions=open_positions,
        portfolio=portfolio,
        cd_map=cd_map,
        all_trades=all_trades,
        chron=chron,
        detail_raw=detail_raw,
        feat_raw_map=feat_raw_map,
        valid_long=valid_long,
        valid_short=valid_short,
        directional=directional,
    )

    log(f"\n[5] TUM YONLU SINYALLER — KARAR ZINCIRI ({len(directional)} adet)")
    extra_keys: list[str] = []
    sample_syms = [s for s, _, _, _ in sorted(directional, key=lambda x: -x[2])]
    for sym, _, _ in alim_uygun_list[:5]:
        if sym not in sample_syms:
            sample_syms.insert(0, sym)
    high_flat: list[tuple[str, float]] = []
    for sym in symbols:
        sig = signals.get(sym)
        if not sig:
            continue
        if str(sig.get("direction")) == "flat" and float(sig.get("confidence", 0)) >= 0.70:
            high_flat.append((sym, float(sig.get("confidence", 0))))
    high_flat.sort(key=lambda x: -x[1])
    for sym, _ in high_flat[:10]:
        if sym not in sample_syms:
            sample_syms.append(sym)
    for sym in sample_syms:
        for k in (
            f"agents:verdict:{sym}",
            f"agents:verdicts:{sym}",
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
        for sym, d, c, r in sorted(near_miss, key=lambda x: -x[2])[:20]:
            log(f"    {sym:14s} {d:5s} conf={c:.0%}  {r[:70]}")

    log(f"\n[5c] YUKSEK CONF FLAT — neden yon yok (top {min(15, len(high_flat))})")
    log("  Ensemble conf yuksek ama direction=flat → ajanlar uzlasamadi veya signal_engine bastirdi")
    for sym, c in high_flat[:15]:
        sig = signals.get(sym) or {}
        verdict = jparse(detail_raw.get(f"agents:verdict:{sym}")) or {}
        v_dir = str(verdict.get("direction", "?"))
        v_conf = float(verdict.get("confidence", 0))
        reject = str(sig.get("reject_reason") or "flat signal")[:50]
        log(f"    {sym:14s} sig_conf={c:.0%} agent={v_dir} {v_conf:.0%}  {reject}")

    log("\n[5d] AJAN OYLARI — ALIM_UYGUN + acik pozisyonlar")
    vote_syms = [s for s, _, _ in alim_uygun_list[:5]]
    vote_syms += [
        p.get("symbol") for p in (portfolio.get("positions") or [])
        if p.get("symbol") and p.get("symbol") not in vote_syms
    ]
    vote_keys = []
    for sym in vote_syms:
        k = f"agents:verdicts:{sym}"
        if k not in detail_raw:
            vote_keys.append(k)
    if vote_keys:
        detail_raw.update(mget_map(vote_keys, "votes"))
    for sym in vote_syms[:12]:
        votes = jparse(detail_raw.get(f"agents:verdicts:{sym}"))
        if not votes:
            continue
        if isinstance(votes, dict):
            votes = votes.get("votes") or votes.get("agents") or []
        if not isinstance(votes, list):
            continue
        parts = []
        for v in votes[:9]:
            if isinstance(v, dict):
                parts.append(f"{v.get('agent','?')[:8]}={str(v.get('signal',v.get('direction','?')))[:5]}"
                             f"@{float(v.get('confidence',0)):.0%}")
        if parts:
            log(f"    {sym}: {' | '.join(parts)}")

    log("\n[6] SHADOW SLOT ANALIZI")
    pos_keys_raw = rc("KEYS", "shadow:positions:*")
    pos_keys = [k for k in pos_keys_raw.splitlines() if k and k != "(nil)"]
    shadow_pos_map: dict[str, dict] = {}
    if pos_keys:
        pos_raw = mget_map(pos_keys, "shadow-pos")
        sc = shadow_counts_from_keys(pos_keys)
        log(f"  Redis shadow pozisyon key: {len(pos_keys)}")
        log(f"  Shadow basina acik: {dict(sc)}")
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
        f"  Formul: margin = min(port*{risk_lim['max_position_pct']*100:.0f}%, slot*0.92) "
        f"* min(conf,85%)  |  notional = margin × lev  |  "
        f"acilis: BUY/SELL_SHORT, kapanis: SELL/BUY_COVER"
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
    log(f"  Kayit sayisi: {len(all_trades)} (ozet [4z] bolumunde)")

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

    log("\n[8b] CIKIS NEDENI DAGILIMI (top 15)")
    for reason, n in exit_ctr.most_common(15):
        log(f"    {n:4d}x  {reason}")
    log(f"  Tutma suresi: {dict(hold_buckets)}")

    fee_side = float(env_flags.get("TRADE_FEE_PCT_PER_SIDE", "0.001") or 0.001)
    log(f"\n[8c] SON 5 ISLEM — YASAM DONGUSU (giris→cikis)")
    for t in all_trades[:5]:
        sym = t.get("symbol", "?")
        ladder = t.get("ladder") or {}
        entry_sig = t.get("entry_signal") or {}
        lev = float(ladder.get("leverage", 1) or 1)
        margin = float(t.get("size_usd", 0) or 0)
        notional = float(ladder.get("notional_usd", margin * lev) or margin * lev)
        fee_est = notional * fee_side * 2
        opened = float(t.get("opened_at", t.get("entry_time", 0)) or 0)
        closed = float(t.get("closed_at", 0) or 0)
        log(f"  {sym} {t.get('direction')} "
            f"acilis={time.strftime('%H:%M:%S', time.localtime(opened)) if opened else '?'} "
            f"kapanis={time.strftime('%H:%M:%S', time.localtime(closed)) if closed else '?'} "
            f"hold={int(float(t.get('hold_seconds',0)))}s")
        log(f"    margin=${margin:.0f} lev={lev:.0f}x notional=${notional:.0f} "
            f"fee_tahmini=${fee_est:.2f} (2×{fee_side*100:.2f}%)")
        log(f"    giris_conf={float(ladder.get('entry_confidence', entry_sig.get('confidence',0))):.0%} "
            f"sl={float(ladder.get('stop_loss_pct',0)):.1f}% tp={float(ladder.get('take_profit_pct',0)):.1f}%")
        log(f"    cikis: {t.get('exit_reason') or t.get('close_reason') or '(bos)'} "
            f"pnl={pct(float(t.get('pnl_pct',0)))} ${float(t.get('pnl_usdt',0)):+.2f}")
        if entry_sig.get("consensus_reasoning"):
            log(f"    giris_gerekce: {str(entry_sig.get('consensus_reasoning'))[:100]}")

    if all_trades and not chron:
        chron = sorted(all_trades, key=lambda t: float(t.get("closed_at", 0)))
    if chron:
        recent = chron[-50:] if len(chron) > 50 else chron
        old = chron[:-50] if len(chron) > 50 else []

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
        dir_pnl: dict[str, float] = defaultdict(float)
        dir_n: dict[str, int] = defaultdict(int)
        for t in chron:
            d = str(t.get("direction", "?"))
            dir_pnl[d] += float(t.get("pnl_usdt", 0))
            dir_n[d] += 1
        log("\n[9c] PNL YON BAZLI")
        for d, pnl_u in sorted(dir_pnl.items(), key=lambda x: x[1]):
            log(f"    {d:6s} ${pnl_u:+.2f} ({dir_n[d]} islem)")
        churn = sum(1 for t in chron if int(float(t.get("hold_seconds", 0))) < 120)
        log(f"  Churn <2dk:       {churn}/{len(chron)} ({churn/len(chron)*100:.1f}%)")
        avg_hold = sum(int(float(t.get("hold_seconds", 0))) for t in chron) / len(chron)
        log(f"  Ort tutma:        {avg_hold:.0f}s ({avg_hold/60:.1f} dk)")
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
    log(f"  Feature eksik:     {no_feature}/{len(symbols)}")
    log(f"  Sinyal eksik:      {no_signal}/{len(symbols)}")
    log(f"  Context ok:        {len(ctx_raw_map) - sum(1 for v in ctx_raw_map.values() if not v)}/{len(symbols)}")
    alim_fiyat_sifir = 0
    for sym, _, _ in alim_uygun_list:
        p = ticker_price(
            detail_raw.get(f"binance:ticker:{sym.lower()}"),
            feat_raw_map.get(f"features:latest:{sym}"),
            None,
        )
        if p <= 0:
            alim_fiyat_sifir += 1
    if alim_uygun_list:
        log(f"  ALIM_UYGUN fiyat=0: {alim_fiyat_sifir}/{len(alim_uygun_list)} "
            f"(>0 ise shadow kod hatasi, =0 ise WS)")

    log("\n[11] ONCELIKLI AKSIYONLAR (etki sirasi)")
    actions: list[str] = []
    if open_n >= max_open:
        actions.append(
            f"KRITIK: Shadow {open_n}/{max_open} dolu — yeni alim IMKANSIZ. "
            f"Acik: {', '.join(open_syms)}. Kapanis veya max_hold beklenmeli."
        )
    if len(alim_uygun_list) > 0 and open_n < max_open:
        cooled_alim = []
        for sym, d, c in alim_uygun_list:
            cd_raw = cd_map.get(f"trade:cooldown:shadow:{sym.upper()}")
            if cd_raw and time.time() < float(cd_raw or 0):
                cooled_alim.append(sym)
        if cooled_alim:
            actions.append(
                f"{len(alim_uygun_list)} ALIM_UYGUN — {len(cooled_alim)} sembol cooldown'da "
                f"({', '.join(cooled_alim[:5])}) — shadow tick beklenir, kod hatasi degil"
            )
        elif live_eq < configured_cap * 0.25:
            actions.append(
                f"KRITIK: Canli equity ${live_eq:,.0f} << kasa ${configured_cap:,.0f} — "
                f"islem boyutu ~${live_eq/max(max_open,1):.0f}/slot. Dashboard'dan kasayi kaydedin veya DEPLOY."
            )
        else:
            actions.append(
                f"{len(alim_uygun_list)} ALIM_UYGUN, {open_n}/{max_open} acik — "
                f"shadow tick (3s) ile acilmasi beklenir. En iyi: {alim_uygun_list[0][0]} {alim_uygun_list[0][2]:.0%}"
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

    llm_ozet = {
        "ts": int(time.time()),
        "deploy": deploy,
        "rules": {k: rules.get(k) for k in rules if k != "error"},
        "portfolio_usd": configured_cap,
        "live_equity_usd": live_eq,
        "equity_source": eq_source,
        "open_n": open_n,
        "max_open": max_open,
        "pipeline": {
            "symbols": len(symbols),
            "features": len(features),
            "signals": len(signals),
            "valid_long": len(valid_long),
            "valid_short": len(valid_short),
            "directional": len(directional),
            "dir_counts": dict(dir_ctr),
            "conf_buckets": dict(conf_buckets),
            "top_rejects": reject_ctr.most_common(8),
            "regime_top": regime_ctr.most_common(6),
        },
        "valid_signals": [
            {"symbol": s, **signal_decision_fields(signals.get(s))}
            for s, _ in valid_long + valid_short
        ],
        "alim_uygun": [
            {"symbol": s, "direction": d, "confidence": c}
            for s, d, c in alim_uygun_list
        ],
        "blockers": block_all.most_common(12),
        "open_positions": portfolio.get("positions") or [],
        "profitability": {
            "total_trades": len(chron) if chron else 0,
            "win_rate_all": round(wr(chron) * 100, 1) if chron else None,
            "empty_exit_count": empty_exit,
        } if chron else {},
        "actions": actions,
        "data_quality": {
            "no_feature": no_feature,
            "no_signal": no_signal,
            "ticker_zero_sample": ticker_zero,
            "alim_uygun_price_zero": alim_fiyat_sifir,
        },
    }
    log("\n[12] LLM_JSON_OZET (makine okunur — gelistirme icin)")
    log(json.dumps(llm_ozet, ensure_ascii=False, default=str))

    elapsed = time.time() - t0
    log(f"\n  Sure: {elapsed:.1f} sn")
    log("=" * 72)


if __name__ == "__main__":
    main()
