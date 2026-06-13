"""
Kârlılık kuralları — SHADOW_A autopsy bulgularına göre:
- %67 win rate + -%99 getiri = küçük kazanç (+%0.3 net) vs büyük zarar (-%5..-%9)
- BEATUSDT churn: guard kapat → 5sn sonra yeniden aç → büyük zarar
- Paper min conf %35 çok düşük → gürültü girişleri
"""

from __future__ import annotations

import os
import time

# Giriş — kâr odaklı: düşük conf gürültü girişi üretiyordu (WR %23, churn <2dk)
SHADOW_MIN_CONFIDENCE = float(os.getenv("SHADOW_MIN_CONFIDENCE", "0.62"))
OMS_MIN_CONFIDENCE = float(os.getenv("OMS_MIN_CONFIDENCE", "0.60"))
PAPER_MIN_SIGNAL_CONFIDENCE = float(os.getenv("PAPER_MIN_SIGNAL_CONFIDENCE", "0.60"))
MIN_AGENT_ALIGN_CONF = float(os.getenv("MIN_AGENT_ALIGN_CONF", "0.38"))
"""Ajan FLAT iken giriş — teşhis: sinyal %67–76, ajan %12–28 FLAT → kötü WR."""
MIN_SIGNAL_WITHOUT_AGENT = float(os.getenv("MIN_SIGNAL_WITHOUT_AGENT", "0.72"))
SLOT_ROTATE_MIN_CONF = float(os.getenv("SLOT_ROTATE_MIN_CONF", "0.68"))

# Risk/ödül — stop 1.2%, ilk TP en az 1.5% (R:R ≥ 1.25)
DEFAULT_STOP_LOSS_PCT = float(os.getenv("DEFAULT_STOP_LOSS_PCT", "1.2"))
DEFAULT_TAKE_PROFIT_TIERS = os.getenv("DEFAULT_TAKE_PROFIT_TIERS", "1.5,3,6,12")
MIN_RR_RATIO = float(os.getenv("MIN_RR_RATIO", "1.25"))

# Guard
GUARD_TAKE_PROFIT_PCT = float(os.getenv("GUARD_TAKE_PROFIT_PCT", "1.2"))
GUARD_MAX_LOSS_PCT = float(os.getenv("GUARD_MAX_LOSS_PCT", "1.0"))
GUARD_EMERGENCY_LOSS_PCT = float(os.getenv("GUARD_EMERGENCY_LOSS_PCT", "1.8"))

# Churn önleme
SYMBOL_COOLDOWN_SEC = int(os.getenv("SYMBOL_COOLDOWN_SEC", "900"))
PAPER_SYMBOL_COOLDOWN_SEC = int(os.getenv("PAPER_SYMBOL_COOLDOWN_SEC", "600"))
LOSS_COOLDOWN_SEC = int(os.getenv("LOSS_COOLDOWN_SEC", "1800"))

# Breakeven — küçük kârı koru, geri dönüşte erken çık
BREAKEVEN_ACTIVATE_PCT = float(os.getenv("BREAKEVEN_ACTIVATE_PCT", "0.35"))
BREAKEVEN_FLOOR_PCT = float(os.getenv("BREAKEVEN_FLOOR_PCT", "0.08"))
SHADOW_MAX_OPEN = int(os.getenv("SHADOW_MAX_OPEN", "30"))
SHADOW_HARD_STOP_PCT = float(os.getenv("SHADOW_HARD_STOP_PCT", "1.2"))

# Uzun tutulan pozisyon slot kilidi — paper'da 1 saat sonra zorla kapat
MAX_POSITION_HOLD_SEC = int(os.getenv("MAX_POSITION_HOLD_SEC", "3600"))
STALE_VERDICT_HOLD_SEC = int(os.getenv("STALE_VERDICT_HOLD_SEC", "1800"))
STALE_EXIT_MIN_LOSS_PCT = float(os.getenv("STALE_EXIT_MIN_LOSS_PCT", "-0.25"))
STALE_EXIT_GRACE_SEC = int(os.getenv("STALE_EXIT_GRACE_SEC", "900"))
RECOVERY_HOLD_UPNL_MIN = float(os.getenv("RECOVERY_HOLD_UPNL_MIN", "-0.55"))
RECOVERY_HOLD_UPNL_MAX = float(os.getenv("RECOVERY_HOLD_UPNL_MAX", "0.35"))

# Zarardan kâra — akıllı çıkış (scratch / soft stop / toparlanma)
SCRATCH_EXIT_MAX_LOSS_PCT = float(os.getenv("SCRATCH_EXIT_MAX_LOSS_PCT", "-0.12"))
SOFT_STOP_LOSS_PCT = float(os.getenv("SOFT_STOP_LOSS_PCT", "-0.85"))
RECOVERY_BOUNCE_MIN_PCT = float(os.getenv("RECOVERY_BOUNCE_MIN_PCT", "0.12"))
LOSS_TO_PROFIT_TARGET_PCT = float(os.getenv("LOSS_TO_PROFIT_TARGET_PCT", "0.05"))
RECOVERY_SIGNAL_MIN_CONF = float(os.getenv("RECOVERY_SIGNAL_MIN_CONF", "0.55"))
TRAIL_TIER_1_PEAK = float(os.getenv("TRAIL_TIER_1_PEAK", "1.5"))
TRAIL_TIER_1_GIVE = float(os.getenv("TRAIL_TIER_1_GIVE", "0.4"))
TRAIL_TIER_2_PEAK = float(os.getenv("TRAIL_TIER_2_PEAK", "3.0"))
TRAIL_TIER_2_GIVE = float(os.getenv("TRAIL_TIER_2_GIVE", "0.8"))
TRAIL_TIER_3_PEAK = float(os.getenv("TRAIL_TIER_3_PEAK", "6.0"))
TRAIL_TIER_3_GIVE = float(os.getenv("TRAIL_TIER_3_GIVE", "1.5"))
MIN_RECOVERY_HOLD_SEC = int(os.getenv("MIN_RECOVERY_HOLD_SEC", "300"))

# Churn / düşük kalite coinler (autopsy + teşhis)
_DEFAULT_BLACKLIST = (
    "ESPORTSUSDT,GTCUSDT,DEXEUSDT,AIOUSDT,BRUSDT,BEATUSDT,NAORISUSDT,"
    "STGUSDT,INXUSDT,KATUSDT"
)
SYMBOL_BLACKLIST: frozenset[str] = frozenset(
    s.strip().upper()
    for s in os.getenv("SYMBOL_BLACKLIST", _DEFAULT_BLACKLIST).split(",")
    if s.strip()
)

CONF_EPSILON = 1e-6
COOLDOWN_KEY_PREFIX = "trade:cooldown:"


def profit_tiers() -> list[float]:
    tiers = sorted({float(x.strip()) for x in DEFAULT_TAKE_PROFIT_TIERS.split(",") if x.strip()})
    return tiers or [1.5, 3.0, 6.0, 12.0]


def cooldown_key(symbol: str, source: str = "shadow") -> str:
    return f"{COOLDOWN_KEY_PREFIX}{source}:{symbol.upper()}"


def is_on_cooldown(cooldown_until: float | None) -> bool:
    if not cooldown_until:
        return False
    return time.time() < float(cooldown_until)


def conf_meets(confidence: float, minimum: float) -> bool:
    """0.58 vs 0.58 float hatasını önler."""
    return float(confidence) + CONF_EPSILON >= float(minimum)


def is_blacklisted(symbol: str) -> bool:
    return symbol.upper() in SYMBOL_BLACKLIST


def paper_cooldown_sec() -> int:
    return PAPER_SYMBOL_COOLDOWN_SEC


def rr_ok(stop_pct: float, tp_pct: float) -> bool:
    if stop_pct <= 0 or tp_pct <= 0:
        return False
    return (tp_pct / stop_pct) >= MIN_RR_RATIO


def entry_allowed(
    confidence: float,
    *,
    stop_pct: float = 0,
    tp_pct: float = 0,
    min_conf: float | None = None,
) -> tuple[bool, str]:
    mc = min_conf if min_conf is not None else SHADOW_MIN_CONFIDENCE
    if not conf_meets(confidence, mc):
        return False, f"confidence {confidence:.2f} < {mc:.2f}"
    if stop_pct > 0 and tp_pct > 0 and not rr_ok(stop_pct, tp_pct):
        return False, f"R:R {tp_pct/stop_pct:.2f} < {MIN_RR_RATIO}"
    return True, "ok"


def agent_entry_ok(
    direction: str,
    verdict: dict | None,
    signal_conf: float = 0,
) -> tuple[bool, str]:
    """
    Giriş kapısı — sinyal güçlü olsa bile ajan FLAT/düşük ise blokla.
    Teşhis: LONG %76 + ajan FLAT %12 → agent_neutral ile açılıyordu → WR %18.
    """
    sig = float(signal_conf or 0)
    if not verdict:
        if sig >= MIN_SIGNAL_WITHOUT_AGENT:
            return True, "no_verdict_high_signal"
        return False, f"no_verdict_need_{MIN_SIGNAL_WITHOUT_AGENT:.0%}_got_{sig:.0%}"

    v_dir = str(verdict.get("direction", "flat"))
    v_conf = float(verdict.get("confidence", 0) or 0)

    if v_dir in ("long", "short") and v_dir != direction and v_conf >= MIN_AGENT_ALIGN_CONF:
        return False, f"agent_opposes_{v_dir}_{v_conf:.0%}"

    if v_dir == direction and v_conf >= MIN_AGENT_ALIGN_CONF:
        return True, f"agent_aligned_{v_conf:.0%}"

    if v_dir == "flat" and v_conf >= MIN_AGENT_ALIGN_CONF:
        return False, f"agent_flat_high_{v_conf:.0%}"

    if v_dir == "flat":
        if sig >= MIN_SIGNAL_WITHOUT_AGENT:
            return True, f"signal_strong_{sig:.0%}_agent_flat_{v_conf:.0%}"
        return False, f"agent_flat_{v_conf:.0%}_signal_{sig:.0%}_weak"

    if v_dir == direction and v_conf < MIN_AGENT_ALIGN_CONF:
        if sig >= MIN_SIGNAL_WITHOUT_AGENT:
            return True, f"weak_agent_same_dir_sig_{sig:.0%}"
        return False, f"agent_weak_{v_conf:.0%}_signal_{sig:.0%}"

    return False, f"agent_gate_{v_dir}_{v_conf:.0%}"


def update_ladder_tracking(ladder: dict, upnl: float, hold_sec: float) -> dict:
    """Zirve/dip takibi — toparlanma ve trailing için ladder günceller."""
    ladder = dict(ladder or {})
    peak = float(ladder.get("peak_upnl_pct") or upnl)
    trough = float(ladder.get("trough_upnl_pct") if ladder.get("trough_upnl_pct") is not None else upnl)

    if upnl > peak:
        ladder["peak_upnl_pct"] = round(upnl, 4)
        peak = upnl
    if upnl < trough:
        ladder["trough_upnl_pct"] = round(upnl, 4)
        trough = upnl

    bounce = upnl - trough
    ladder["bounce_from_trough_pct"] = round(bounce, 4)

    if peak >= BREAKEVEN_ACTIVATE_PCT:
        ladder["breakeven_armed"] = True

    if trough < -0.05 and bounce >= RECOVERY_BOUNCE_MIN_PCT and upnl < LOSS_TO_PROFIT_TARGET_PCT:
        ladder["recovery_armed"] = True
        ladder["recovery_since_sec"] = float(ladder.get("recovery_since_sec") or hold_sec)

    trail_floor = dynamic_trail_floor(peak, bool(ladder.get("breakeven_armed")))
    if trail_floor > -900:
        ladder["trail_floor_pct"] = round(trail_floor, 4)

    return ladder


def dynamic_trail_floor(peak_upnl: float, breakeven_armed: bool) -> float:
    """Kademeli trailing — zirveden geri verişe göre dinamik taban."""
    if peak_upnl >= TRAIL_TIER_3_PEAK:
        return peak_upnl - TRAIL_TIER_3_GIVE
    if peak_upnl >= TRAIL_TIER_2_PEAK:
        return peak_upnl - TRAIL_TIER_2_GIVE
    if peak_upnl >= TRAIL_TIER_1_PEAK:
        return peak_upnl - TRAIL_TIER_1_GIVE
    if peak_upnl >= BREAKEVEN_ACTIVATE_PCT or breakeven_armed:
        return BREAKEVEN_FLOOR_PCT
    return -999.0


def _signal_supports_recovery(
    sig_dir: str,
    direction: str,
    sig_conf: float,
    v_dir: str,
    v_conf: float,
) -> bool:
    """Zararda toparlanma — sinyal/ajan hâlâ yönü destekliyor mu?"""
    if sig_dir == direction and sig_conf >= RECOVERY_SIGNAL_MIN_CONF:
        return True
    if v_dir == direction and v_conf >= MIN_AGENT_ALIGN_CONF:
        return True
    if sig_dir == direction and v_dir == direction:
        return True
    return False


def recovery_should_hold(
    *,
    hold_sec: float,
    upnl: float,
    peak_upnl: float,
    trough_upnl: float,
    bounce_pct: float,
    sig_dir: str,
    direction: str,
    sig_conf: float = 0,
    v_dir: str = "flat",
    v_conf: float = 0,
    ladder: dict | None = None,
) -> tuple[bool, str]:
    """
    Zararda pozisyonu tut — toparlanma şansı varsa SL/scratch/AI-FLAT çıkışını ertele.
    """
    ladder = ladder or {}
    if upnl >= 0:
        return False, ""

    if RECOVERY_HOLD_UPNL_MIN <= upnl <= RECOVERY_HOLD_UPNL_MAX:
        if _signal_supports_recovery(sig_dir, direction, sig_conf, v_dir, v_conf):
            return True, f"recovery_zone {upnl:+.2f}% + sinyal destek"
        if bounce_pct >= RECOVERY_BOUNCE_MIN_PCT:
            return True, f"recovery_bounce {bounce_pct:+.2f}% from trough"

    if ladder.get("recovery_armed") and upnl < LOSS_TO_PROFIT_TARGET_PCT:
        rec_since = float(ladder.get("recovery_since_sec") or 0)
        if hold_sec - rec_since < STALE_EXIT_GRACE_SEC:
            return True, f"recovery_armed → hedef +{LOSS_TO_PROFIT_TARGET_PCT:.2f}%"

    if upnl > SCRATCH_EXIT_MAX_LOSS_PCT and upnl < 0.12:
        if bounce_pct >= RECOVERY_BOUNCE_MIN_PCT * 0.75:
            return True, f"near_breakeven_bounce {bounce_pct:+.2f}%"

    if trough < -0.3 and bounce_pct >= RECOVERY_BOUNCE_MIN_PCT:
        if _signal_supports_recovery(sig_dir, direction, sig_conf, v_dir, v_conf):
            return True, f"deep_recovery {trough:+.2f}%→{upnl:+.2f}%"

    if hold_sec < MIN_RECOVERY_HOLD_SEC and upnl > SOFT_STOP_LOSS_PCT:
        if sig_dir == direction and sig_conf >= 0.50:
            return True, f"early_hold aligned {sig_conf:.0%}"

    return False, ""


def evaluate_position_exit(
    *,
    hold_sec: float,
    upnl: float,
    direction: str,
    ladder: dict,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    sig_dir: str = "flat",
    sig_conf: float = 0,
    v_dir: str = "flat",
    v_conf: float = 0,
    guard_action: str = "hold",
    crisis_level: int = 0,
) -> tuple[str, str, str]:
    """
    Birleşik çıkış motoru — shadow + guard + dashboard.
    Returns: (action, reason, exit_kind)
    action: hold | close | emergency_close
    exit_kind: guard | tp | sl | soft_stop | scratch | breakeven | trail | stale | recovery_profit | max_hold | signal_reverse
    """
    sl = float(sl_pct if sl_pct is not None else DEFAULT_STOP_LOSS_PCT)
    tp = float(tp_pct if tp_pct is not None else (profit_tiers()[0] if profit_tiers() else 1.5))
    peak = float(ladder.get("peak_upnl_pct") or upnl)
    trough = float(ladder.get("trough_upnl_pct") if ladder.get("trough_upnl_pct") is not None else upnl)
    bounce = float(ladder.get("bounce_from_trough_pct") or (upnl - trough))
    breakeven_armed = bool(ladder.get("breakeven_armed"))
    trail_floor = float(ladder.get("trail_floor_pct") or dynamic_trail_floor(peak, breakeven_armed))

    if guard_action == "emergency_close":
        return "emergency_close", "guard emergency", "guard"
    if guard_action == "close" and upnl >= LOSS_TO_PROFIT_TARGET_PCT:
        return "close", "guard close (kârda)", "guard"

    if crisis_level >= 4 and upnl < 0:
        return "emergency_close", f"crisis L{crisis_level}", "crisis"

    if hold_sec >= MAX_POSITION_HOLD_SEC:
        return "close", f"max_hold {MAX_POSITION_HOLD_SEC // 60}dk ({upnl:+.2f}%)", "max_hold"

    rec_hold, rec_why = recovery_should_hold(
        hold_sec=hold_sec,
        upnl=upnl,
        peak_upnl=peak,
        trough_upnl=trough,
        bounce_pct=bounce,
        sig_dir=sig_dir,
        direction=direction,
        sig_conf=sig_conf,
        v_dir=v_dir,
        v_conf=v_conf,
        ladder=ladder,
    )

    if ladder.get("recovery_armed") and upnl >= LOSS_TO_PROFIT_TARGET_PCT:
        return "close", f"loss_to_profit +{upnl:.2f}% (dip {trough:+.2f}%)", "recovery_profit"

    if trail_floor > -900 and hold_sec >= 120 and upnl <= trail_floor and peak >= BREAKEVEN_ACTIVATE_PCT:
        return "close", f"trail_stop zirve {peak:+.2f}% → {upnl:+.2f}% (taban {trail_floor:+.2f}%)", "trail"

    if breakeven_armed and hold_sec >= 120 and upnl <= BREAKEVEN_FLOOR_PCT and not rec_hold:
        return "close", f"breakeven_stop zirve {peak:+.2f}% → {upnl:+.2f}%", "breakeven"

    if upnl >= tp:
        return "close", f"take_profit %{tp:.1f} ({upnl:+.2f}%)", "tp"

    for tier in sorted(profit_tiers(), reverse=True):
        if upnl >= tier:
            return "close", f"profit_tier %{tier:g} ({upnl:+.2f}%)", "tp"

    should_stale, stale_why = stale_flat_should_exit(
        hold_sec=hold_sec,
        upnl=upnl,
        peak_upnl=peak,
        sig_dir=sig_dir,
        direction=direction,
        v_dir=v_dir,
        v_conf=v_conf,
    )
    if should_stale:
        if rec_hold and upnl > STALE_EXIT_MIN_LOSS_PCT:
            return "hold", f"stale_deferred — {rec_why}", "hold"
        if upnl >= GUARD_TAKE_PROFIT_PCT * 0.75:
            return "close", f"stale_take_profit — {stale_why}", "stale"
        if SCRATCH_EXIT_MAX_LOSS_PCT < upnl <= STALE_EXIT_MIN_LOSS_PCT:
            return "close", f"scratch_exit {upnl:+.2f}% (stale, toparlanma yok)", "scratch"
        return "close", f"stale_flat — {stale_why}", "stale"

    if (
        sig_dir in ("long", "short")
        and sig_dir != direction
        and sig_conf >= RECOVERY_SIGNAL_MIN_CONF
        and hold_sec >= 45
        and not rec_hold
    ):
        return "close", f"signal_reverse {sig_dir} {sig_conf:.0%}", "signal_reverse"

    if v_dir in ("long", "short") and v_dir != direction and v_conf >= MIN_AGENT_ALIGN_CONF and not rec_hold:
        if upnl < SOFT_STOP_LOSS_PCT or hold_sec >= STALE_VERDICT_HOLD_SEC // 2:
            return "close", f"agent_opposes {v_dir} {v_conf:.0%}", "signal_reverse"

    if upnl <= -sl and not rec_hold:
        return "close", f"hard_stop %{sl:.1f} ({upnl:+.2f}%)", "sl"

    if upnl <= SOFT_STOP_LOSS_PCT and not rec_hold:
        opposed = (
            (sig_dir in ("long", "short") and sig_dir != direction)
            or (v_dir in ("long", "short") and v_dir != direction and v_conf >= 0.25)
        )
        if opposed or bounce < RECOVERY_BOUNCE_MIN_PCT * 0.5:
            return "close", f"soft_stop {upnl:+.2f}% (ters sinyal/dip)", "soft_stop"

    if (
        v_dir == "flat"
        and v_conf >= 0.45
        and sig_dir == "flat"
        and hold_sec >= STALE_VERDICT_HOLD_SEC // 2
        and not rec_hold
        and upnl < 0
        and upnl <= SCRATCH_EXIT_MAX_LOSS_PCT
    ):
        return "close", f"ai_flat_scratch {upnl:+.2f}%", "scratch"

    if rec_hold:
        return "hold", rec_why, "recovery_hold"

    return "hold", f"izleniyor {upnl:+.2f}%", "hold"


def stale_flat_should_exit(
    *,
    hold_sec: float,
    upnl: float,
    peak_upnl: float,
    sig_dir: str,
    direction: str,
    v_dir: str = "flat",
    v_conf: float = 0,
) -> tuple[bool, str]:
    """
    stale_flat_verdict — fee churn önleme: +0% civarı hemen kapatma, zarara recovery süresi.
    """
    if hold_sec < STALE_VERDICT_HOLD_SEC:
        return False, ""

    stale = (
        sig_dir == "flat"
        or (sig_dir in ("long", "short") and sig_dir != direction)
        or (v_dir == "flat" and v_conf >= 0.15)
    )
    if not stale:
        return False, ""

    grace_end = STALE_VERDICT_HOLD_SEC + STALE_EXIT_GRACE_SEC

    if upnl >= GUARD_TAKE_PROFIT_PCT * 0.75:
        return True, f"stale_take_profit ({upnl:+.2f}%)"

    if peak_upnl >= BREAKEVEN_ACTIVATE_PCT and upnl >= BREAKEVEN_FLOOR_PCT:
        return False, "breakeven_hold"

    if RECOVERY_HOLD_UPNL_MIN <= upnl <= RECOVERY_HOLD_UPNL_MAX and hold_sec < grace_end:
        return False, "recovery_grace"

    if upnl > STALE_EXIT_MIN_LOSS_PCT and upnl < 0.12 and hold_sec < grace_end:
        return False, "near_breakeven_grace"

    if upnl <= STALE_EXIT_MIN_LOSS_PCT:
        return True, f"stale_flat_loss ({upnl:+.2f}%)"

    if hold_sec >= grace_end:
        return True, f"stale_flat_timeout ({upnl:+.2f}%)"

    return False, ""


def _fmt_dur(sec: float) -> str:
    s = max(0, int(sec))
    h, rem = divmod(s, 3600)
    m, r = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{r:02d}"
    return f"{m}:{r:02d}"


def _stale_exit_candidate(
    hold_sec: float,
    upnl: float,
    peak: float,
    sig_dir: str,
    direction: str,
    v_dir: str,
    v_conf: float,
    now: float,
) -> dict | None:
    stale_ctx = (
        sig_dir == "flat"
        or (sig_dir in ("long", "short") and sig_dir != direction)
        or (v_dir == "flat" and v_conf >= 0.15)
    )
    grace_end = STALE_VERDICT_HOLD_SEC + STALE_EXIT_GRACE_SEC

    if hold_sec < STALE_VERDICT_HOLD_SEC:
        if not stale_ctx:
            return None
        remain = STALE_VERDICT_HOLD_SEC - hold_sec
        return {
            "priority": 8,
            "trigger": "stale_window",
            "label": "Flat/ajan limiti",
            "countdown_sec": remain,
            "estimated_close_at": now + remain,
            "urgency": "imminent" if remain < 300 else "normal",
            "detail": f"Sinyal {sig_dir} · ajan {v_dir} {v_conf:.0%} → {_fmt_dur(remain)} sonra stale",
        }

    if not stale_ctx:
        return None

    if upnl >= GUARD_TAKE_PROFIT_PCT * 0.75:
        return {
            "priority": 2,
            "trigger": "stale_take_profit",
            "label": "Stale kâr çıkışı",
            "countdown_sec": 0,
            "estimated_close_at": now,
            "urgency": "now",
            "detail": f"Stale + uPnL {upnl:+.2f}% ≥ TP eşiği",
        }

    if peak >= BREAKEVEN_ACTIVATE_PCT and upnl >= BREAKEVEN_FLOOR_PCT:
        to_max = MAX_POSITION_HOLD_SEC - hold_sec
        return {
            "priority": 12,
            "trigger": "breakeven_stale_hold",
            "label": "Breakeven koruması",
            "countdown_sec": max(60, to_max),
            "estimated_close_at": now + max(60, to_max),
            "urgency": "normal",
            "detail": f"Zirve +{peak:.2f}% — stale ertelendi, max {_fmt_dur(to_max)}",
        }

    if RECOVERY_HOLD_UPNL_MIN <= upnl <= RECOVERY_HOLD_UPNL_MAX and hold_sec < grace_end:
        remain = grace_end - hold_sec
        return {
            "priority": 6,
            "trigger": "recovery_grace",
            "label": "Toparlanma süresi",
            "countdown_sec": remain,
            "estimated_close_at": now + remain,
            "urgency": "imminent" if remain < 180 else "normal",
            "detail": f"uPnL {upnl:+.2f}% — grace {_fmt_dur(remain)}",
        }

    if upnl > STALE_EXIT_MIN_LOSS_PCT and upnl < 0.12 and hold_sec < grace_end:
        remain = grace_end - hold_sec
        return {
            "priority": 7,
            "trigger": "near_breakeven_grace",
            "label": "Başabaş bekleme",
            "countdown_sec": remain,
            "estimated_close_at": now + remain,
            "urgency": "imminent" if remain < 180 else "normal",
            "detail": f"Zarar sınırı öncesi — {_fmt_dur(remain)} grace",
        }

    if upnl <= STALE_EXIT_MIN_LOSS_PCT:
        return {
            "priority": 3,
            "trigger": "stale_flat_loss",
            "label": "Stale zarar",
            "countdown_sec": 0,
            "estimated_close_at": now,
            "urgency": "now",
            "detail": f"Stale zarar eşiği {upnl:+.2f}%",
        }

    if hold_sec >= grace_end:
        return {
            "priority": 4,
            "trigger": "stale_flat_timeout",
            "label": "Stale timeout",
            "countdown_sec": 0,
            "estimated_close_at": now,
            "urgency": "now",
            "detail": f"Grace bitti — stale kapanış ({upnl:+.2f}%)",
        }

    remain = grace_end - hold_sec
    return {
        "priority": 7,
        "trigger": "stale_grace",
        "label": "Stale grace",
        "countdown_sec": remain,
        "estimated_close_at": now + remain,
        "urgency": "imminent" if remain < 300 else "normal",
        "detail": f"Flat/ajan stale — en geç {_fmt_dur(remain)}",
    }


def compute_exit_estimate(
    *,
    entry_time: float,
    direction: str,
    upnl: float,
    peak_upnl: float = 0.0,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    sig_dir: str = "flat",
    v_dir: str = "flat",
    v_conf: float = 0.0,
    breakeven_armed: bool = False,
    guard_action: str = "hold",
    now: float | None = None,
) -> dict:
    """Dashboard tahmini satış — profit_rules + shadow hard stop ile uyumlu."""
    now = now or time.time()
    sl = float(sl_pct if sl_pct is not None else DEFAULT_STOP_LOSS_PCT)
    tp = float(tp_pct if tp_pct is not None else (profit_tiers()[0] if profit_tiers() else 1.5))
    hold_sec = now - entry_time if entry_time > 0 else 0.0
    peak = peak_upnl if peak_upnl else upnl
    max_remain = max(0.0, MAX_POSITION_HOLD_SEC - hold_sec)
    cands: list[dict] = []

    if guard_action in ("emergency_close", "close"):
        cands.append({
            "priority": 1,
            "trigger": "guard",
            "label": "GUARD kapanış",
            "countdown_sec": 0,
            "estimated_close_at": now,
            "urgency": "now",
            "detail": "Acil kapanış" if guard_action == "emergency_close" else "Guard satış önerisi",
        })

    if upnl <= -sl:
        cands.append({
            "priority": 2,
            "trigger": "stop_loss",
            "label": "STOP (SL)",
            "countdown_sec": 0,
            "estimated_close_at": now,
            "urgency": "now",
            "detail": f"SL -{sl:.1f}% aşıldı ({upnl:+.2f}%)",
        })
    elif upnl <= -(sl - 0.2):
        eta = max(20.0, ((sl + upnl) / 0.04) * 30)
        cands.append({
            "priority": 3,
            "trigger": "stop_near",
            "label": "STOP yakın",
            "countdown_sec": eta,
            "estimated_close_at": now + eta,
            "urgency": "imminent",
            "detail": f"SL -{sl:.1f}%'ye {sl + upnl:.2f}% kaldı",
        })

    if upnl >= tp:
        cands.append({
            "priority": 2,
            "trigger": "take_profit",
            "label": "TP (kâr)",
            "countdown_sec": 0,
            "estimated_close_at": now,
            "urgency": "now",
            "detail": f"TP +{tp:.1f}% hedefi ({upnl:+.2f}%)",
        })
    elif upnl >= tp - 0.25:
        cands.append({
            "priority": 3,
            "trigger": "tp_near",
            "label": "TP yakın",
            "countdown_sec": 25,
            "estimated_close_at": now + 25,
            "urgency": "imminent",
            "detail": f"TP +{tp:.1f}%'ye {tp - upnl:.2f}% kaldı",
        })

    if breakeven_armed and hold_sec >= 120 and upnl <= BREAKEVEN_FLOOR_PCT:
        cands.append({
            "priority": 4,
            "trigger": "breakeven",
            "label": "Breakeven stop",
            "countdown_sec": 0,
            "estimated_close_at": now,
            "urgency": "now",
            "detail": f"Zirve +{peak:.2f}% → şimdi {upnl:+.2f}%",
        })

    if sig_dir not in ("flat", direction) and hold_sec >= 45:
        cands.append({
            "priority": 5,
            "trigger": "signal_reverse",
            "label": "Sinyal ters",
            "countdown_sec": 20,
            "estimated_close_at": now + 20,
            "urgency": "imminent",
            "detail": f"Anlık sinyal {sig_dir} — ters yön kapanışı",
        })

    stale = _stale_exit_candidate(hold_sec, upnl, peak, sig_dir, direction, v_dir, v_conf, now)
    if stale:
        cands.append(stale)

    if max_remain > 0 and entry_time > 0:
        cands.append({
            "priority": 11,
            "trigger": "max_hold",
            "label": "Max tutma",
            "countdown_sec": max_remain,
            "estimated_close_at": now + max_remain,
            "urgency": "imminent" if max_remain < 300 else "normal",
            "detail": f"Zorunlu kapanış {_fmt_dur(max_remain)} ({MAX_POSITION_HOLD_SEC // 60}dk)",
        })
    elif hold_sec >= MAX_POSITION_HOLD_SEC and entry_time > 0:
        cands.append({
            "priority": 6,
            "trigger": "max_hold_over",
            "label": "Max tutma aşıldı",
            "countdown_sec": 0,
            "estimated_close_at": now,
            "urgency": "now",
            "detail": f"{int(hold_sec // 60)}dk — zorunlu kapanış bekleniyor",
        })

    if not cands:
        fallback = max_remain if max_remain > 0 else float(MAX_POSITION_HOLD_SEC)
        return {
            "trigger": "hold",
            "label": "Tutuluyor",
            "countdown_sec": fallback,
            "estimated_close_at": now + fallback,
            "urgency": "normal",
            "detail": f"SL -{sl:.1f}% · TP +{tp:.1f}%",
            "computed_at": now,
        }

    now_cands = [c for c in cands if c["countdown_sec"] <= 0]
    if now_cands:
        now_cands.sort(key=lambda c: c["priority"])
        w = now_cands[0]
        runner = next(
            (c for c in sorted(cands, key=lambda x: x["countdown_sec"]) if c["countdown_sec"] > 0),
            None,
        )
        out = {**w, "computed_at": now}
        if runner:
            out["secondary"] = f"{runner['label']} {_fmt_dur(runner['countdown_sec'])}"
        return out

    cands.sort(key=lambda c: (c["countdown_sec"], c["priority"]))
    winner = cands[0]
    runner = next((c for c in cands if c["trigger"] != winner["trigger"] and c["countdown_sec"] > winner["countdown_sec"]), None)
    out = {**winner, "computed_at": now}
    if runner:
        out["secondary"] = f"{runner['label']} {_fmt_dur(runner['countdown_sec'])}"
    return out


def cooldown_after_close(pnl_pct: float, *, blacklisted: bool = False) -> int:
    """Zarar sonrası uzun bekleme; kârda daha hızlı yeniden giriş (motor)."""
    if pnl_pct < 0:
        return LOSS_COOLDOWN_SEC if not blacklisted else LOSS_COOLDOWN_SEC * 2
    if pnl_pct >= 0.003:
        return int(os.getenv("WIN_COOLDOWN_SEC", "300"))
    if blacklisted:
        return paper_cooldown_sec()
    return paper_cooldown_sec()


def build_history_record(payload: dict) -> dict:
    """Shadow/OMS kapanışını oms:trade_history formatına çevirir."""
    closed_at = float(payload.get("closed_at", time.time()))
    hold = float(payload.get("hold_seconds", 0) or 0)
    reason = str(
        payload.get("exit_reason")
        or payload.get("close_reason")
        or payload.get("reason")
        or ""
    )[:500]
    if not reason:
        src = str(payload.get("source", "unknown"))
        action = str(payload.get("action", "close"))
        reason = f"{src}:{action}"
    ladder = payload.get("ladder") or {}
    if isinstance(payload.get("entry_signal"), dict):
        es = payload["entry_signal"]
        ladder = ladder or {
            "entry_confidence": es.get("confidence"),
            "stop_loss_pct": es.get("stop_loss_pct"),
            "take_profit_pct": (es.get("take_profit_tiers") or [None])[0],
        }
    return {
        "symbol": payload.get("symbol", ""),
        "direction": payload.get("direction", "long"),
        "action": "close",
        "entry_price": payload.get("entry_price"),
        "exit_price": payload.get("exit_price"),
        "pnl_pct": payload.get("pnl_pct", 0),
        "pnl_usdt": payload.get("pnl_usdt", 0),
        "size_usd": payload.get("size_usd") or ladder.get("margin_usd"),
        "margin_usd": payload.get("margin_usd") or ladder.get("margin_usd"),
        "leverage": payload.get("leverage") or ladder.get("leverage"),
        "fee_total_usd": payload.get("fee_total_usd"),
        "source": payload.get("source", "shadow_system"),
        "shadow_id": payload.get("shadow_id"),
        "timestamp": int(closed_at * 1000),
        "closed_at": closed_at,
        "hold_seconds": hold,
        "ladder": ladder,
        "exit_reason": reason,
        "close_reason": reason,
    }
