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
        if sig >= 0.65 and v_conf >= 0.22:
            return True, f"moderate_consensus_sig_{sig:.0%}_agent_{v_conf:.0%}"
        return False, f"agent_flat_{v_conf:.0%}_signal_{sig:.0%}_weak"

    if v_dir == direction and v_conf < MIN_AGENT_ALIGN_CONF:
        if sig >= MIN_SIGNAL_WITHOUT_AGENT:
            return True, f"weak_agent_same_dir_sig_{sig:.0%}"
        return False, f"agent_weak_{v_conf:.0%}_signal_{sig:.0%}"

    return False, f"agent_gate_{v_dir}_{v_conf:.0%}"


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
