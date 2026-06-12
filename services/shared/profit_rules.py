"""
Kârlılık kuralları — SHADOW_A autopsy bulgularına göre:
- %67 win rate + -%99 getiri = küçük kazanç (+%0.3 net) vs büyük zarar (-%5..-%9)
- BEATUSDT churn: guard kapat → 5sn sonra yeniden aç → büyük zarar
- Paper min conf %35 çok düşük → gürültü girişleri
"""

from __future__ import annotations

import os
import time

# Giriş
SHADOW_MIN_CONFIDENCE = float(os.getenv("SHADOW_MIN_CONFIDENCE", "0.62"))
OMS_MIN_CONFIDENCE = float(os.getenv("OMS_MIN_CONFIDENCE", "0.60"))
PAPER_MIN_SIGNAL_CONFIDENCE = float(os.getenv("PAPER_MIN_SIGNAL_CONFIDENCE", "0.58"))

# Risk/ödül — stop 1.2%, ilk TP en az 1.5% (R:R ≥ 1.25)
DEFAULT_STOP_LOSS_PCT = float(os.getenv("DEFAULT_STOP_LOSS_PCT", "1.2"))
DEFAULT_TAKE_PROFIT_TIERS = os.getenv("DEFAULT_TAKE_PROFIT_TIERS", "1.5,3,6,12")
MIN_RR_RATIO = float(os.getenv("MIN_RR_RATIO", "1.25"))

# Guard
GUARD_TAKE_PROFIT_PCT = float(os.getenv("GUARD_TAKE_PROFIT_PCT", "1.2"))
GUARD_MAX_LOSS_PCT = float(os.getenv("GUARD_MAX_LOSS_PCT", "1.0"))
GUARD_EMERGENCY_LOSS_PCT = float(os.getenv("GUARD_EMERGENCY_LOSS_PCT", "1.8"))

# Churn önleme — kapatınca aynı sembole 30dk girme
SYMBOL_COOLDOWN_SEC = int(os.getenv("SYMBOL_COOLDOWN_SEC", "1800"))
SHADOW_MAX_OPEN = int(os.getenv("SHADOW_MAX_OPEN", "3"))
SHADOW_HARD_STOP_PCT = float(os.getenv("SHADOW_HARD_STOP_PCT", "1.2"))

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
    if confidence < mc:
        return False, f"confidence {confidence:.2f} < {mc:.2f}"
    if stop_pct > 0 and tp_pct > 0 and not rr_ok(stop_pct, tp_pct):
        return False, f"R:R {tp_pct/stop_pct:.2f} < {MIN_RR_RATIO}"
    return True, "ok"
