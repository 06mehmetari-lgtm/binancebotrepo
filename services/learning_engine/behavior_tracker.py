"""
Per-symbol continual learning — observes feature/context/ticker streams,
builds behavioral profiles (regime reactions, drivers, entry/exit hints).
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field

FACTOR_LABELS: dict[str, str] = {
    "rsi_oversold_bounce": "RSI<32 sonrası 3 bar toparlanma",
    "rsi_overbought_drop": "RSI>68 sonrası geri çekilme",
    "bid_pressure_up": "Bid imbalance >0.25 yükseliş",
    "high_funding_fade": "Yüksek funding sonrası short edge",
    "crisis_risk_off": "Kriz L≥2 risk-off hareketi",
    "trade_long_win": "Long işlem kârı",
    "trade_long_loss": "Long işlem zararı",
    "trade_short_win": "Short işlem kârı",
    "trade_short_loss": "Short işlem zararı",
    "profit_take_good": "Kâr kademesi / trailing ile çıkış",
    "early_flat_loss": "AI FLAT ile erken zarar çıkışı",
    "missed_peak": "Zirve kâr kaçırıldı sonra zarar",
}


@dataclass
class TickSample:
    ts: float
    price: float
    regime: str
    rsi: float
    macd_hist: float
    imbalance_5: float
    funding: float
    drift: str
    crisis: int
    volume_ratio: float


@dataclass
class PatternStats:
    hits: int = 0
    misses: int = 0
    total_move_pct: float = 0.0

    @property
    def samples(self) -> int:
        return self.hits + self.misses

    @property
    def win_rate(self) -> float:
        return self.hits / self.samples if self.samples else 0.0

    @property
    def avg_move_pct(self) -> float:
        return self.total_move_pct / max(self.hits, 1)


def _stage_thresholds() -> tuple[int, int, int, int]:
    """L0/L1/L2 minimum updates — hızlı öğrenme modu env ile."""
    if os.getenv("LEARNING_FAST_TRACK", "true").lower() in ("1", "true", "yes"):
        return (15, 80, 250, 4)  # open-position / hot symbols reach L2 faster
    return (40, 200, 600, 4)


def _learning_stage(updates: int, driver_count: int) -> str:
    l0, l1, l2, l3_drv = _stage_thresholds()
    if updates < l0 or driver_count == 0:
        return "L0"
    if updates < l1 or driver_count < 2:
        return "L1"
    if updates < l2 or driver_count < l3_drv:
        return "L2"
    return "L3"


def _depth_score(drivers: list[dict], updates: int) -> int:
    score = min(5, len([d for d in drivers if d.get("samples", 0) >= 8]))
    if updates >= 200:
        score = min(5, score + 1)
    if updates >= 800:
        score = min(5, score + 1)
    return max(1, score)


@dataclass
class SymbolLearner:
    symbol: str
    history: deque = field(default_factory=lambda: deque(maxlen=180))
    patterns: dict[str, PatternStats] = field(default_factory=dict)
    regime_transitions: dict[str, PatternStats] = field(default_factory=dict)
    last_regime: str = "unknown"
    last_price: float = 0.0
    last_drift: str = "STABLE"
    updates: int = 0
    last_lesson_hash: str = ""
    llm_enrich_count: int = 0

    def _pat(self, key: str) -> PatternStats:
        if key not in self.patterns:
            self.patterns[key] = PatternStats()
        return self.patterns[key]

    def _reg(self, key: str) -> PatternStats:
        if key not in self.regime_transitions:
            self.regime_transitions[key] = PatternStats()
        return self.regime_transitions[key]

    def _fingerprint(self) -> dict:
        if len(self.history) < 5:
            return {}
        recent = list(self.history)[-40:]
        n = len(recent)
        return {
            "rsi_avg": round(sum(s.rsi for s in recent) / n, 1),
            "macd_avg": round(sum(s.macd_hist for s in recent) / n, 5),
            "funding_avg": round(sum(s.funding for s in recent) / n, 6),
            "imbalance_avg": round(sum(s.imbalance_5 for s in recent) / n, 3),
            "volume_ratio_avg": round(sum(s.volume_ratio for s in recent) / n, 2),
            "crisis_max": max(s.crisis for s in recent),
            "drift_modes": list({s.drift for s in recent}),
        }

    def record_trade_close(
        self,
        direction: str,
        pnl_pct: float,
        won: bool,
        *,
        imbalance_5: float | None = None,
        funding: float | None = None,
        source: str = "",
        exit_reason: str = "",
        peak_upnl_pct: float | None = None,
        hold_seconds: float = 0,
    ) -> list[str]:
        """Her kapanan işlemden derinlik/funding/çıkış nedeniyle ders."""
        key = f"trade_{direction}_{'win' if won else 'loss'}"
        st = self._pat(key)
        if won:
            st.hits += 1
            st.total_move_pct += abs(pnl_pct) * 100
        else:
            st.misses += 1
        why = exit_reason[:160] if exit_reason else "sinyal/guard"
        lessons: list[str] = [
            f"Kapanış {direction} {'kâr' if won else 'zarar'} {pnl_pct:+.2%} "
            f"(rejim {self.last_regime}, {int(hold_seconds)}sn, neden: {why})"
        ]
        if exit_reason:
            if any(x in exit_reason for x in ("Kâr kademesi", "Kâr hedefi", "Trailing", "Kârda sat", "Kâr koruma")):
                pt = self._pat("profit_take_good")
                pt.hits += 1
                pt.total_move_pct += abs(pnl_pct) * 100
                lessons.append(f"✓ İyi çıkış: {exit_reason[:100]}")
            elif "AI FLAT" in exit_reason and not won:
                ef = self._pat("early_flat_loss")
                ef.misses += 1
                lessons.append(f"✗ Erken FLAT zarar — pozisyon tut veya kârda sat: {exit_reason[:80]}")
        peak = float(peak_upnl_pct or 0)
        if peak > abs(pnl_pct) * 100 + 0.3 and not won:
            mp = self._pat("missed_peak")
            mp.misses += 1
            lessons.append(
                f"Zirve +{peak:.2f}% varken {pnl_pct:+.2%} ile kapandı — trailing sıkılaştır"
            )
        if imbalance_5 is not None:
            side = "bid baskısı" if imbalance_5 > 0.2 else (
                "ask baskısı" if imbalance_5 < -0.2 else "dengeli defter"
            )
            lessons.append(f"imbalance_5={imbalance_5:.2f} → {side}")
            if imbalance_5 > 0.25 and not won and direction == "long":
                self._pat("bid_pressure_up").misses += 1
            elif imbalance_5 < -0.25 and not won and direction == "long":
                self._pat("bid_pressure_up").hits += 1
        if funding is not None and abs(funding) > 0.0004:
            lessons.append(f"funding={funding*100:.3f}% kapanış anı")
        if not won and "breakout" in (exit_reason or "").lower():
            fb = self._pat("false_breakout")
            fb.misses += 1
            lessons.append("false_breakout — düşük hacimde chase yapma, rejim doğrula")
        if not won and pnl_pct < -0.003:
            rc = self._pat("recovery_dca_candidate")
            rc.misses += 1
            lessons.append(
                f"Zarar {pnl_pct:+.2%} — kademeli alış sadece güçlü sinyal+immunity onayı ile; "
                f"tüm bakiyeyi tek coine yatırma (max %15)"
            )
            if "recovery_dca" in source or "DCA" in (exit_reason or ""):
                self._pat("recovery_dca_result").misses += 1
                lessons.append("DCA sonrası zarar — sinyal gücü veya tier sınırını gözden geçir")
        return lessons

    def observe(self, sample: TickSample) -> list[str]:
        """Returns new lesson lines only for meaningful regime shifts (deduped)."""
        new_lessons: list[str] = []
        self.history.append(sample)
        self.updates += 1
        self.last_drift = sample.drift

        if self.last_price > 0 and sample.price > 0:
            move_pct = (sample.price - self.last_price) / self.last_price * 100
        else:
            move_pct = 0.0

        if len(self.history) >= 4:
            past = self.history[-4]
            horizon_move = (sample.price - past.price) / past.price * 100 if past.price else 0

            if past.rsi < 32:
                p = self._pat("rsi_oversold_bounce")
                if horizon_move > 0.15:
                    p.hits += 1
                    p.total_move_pct += horizon_move
                elif horizon_move < -0.15:
                    p.misses += 1
            if past.rsi > 68:
                p = self._pat("rsi_overbought_drop")
                if horizon_move < -0.15:
                    p.hits += 1
                    p.total_move_pct += abs(horizon_move)
                elif horizon_move > 0.15:
                    p.misses += 1

            if past.imbalance_5 > 0.25:
                p = self._pat("bid_pressure_up")
                if horizon_move > 0.1:
                    p.hits += 1
                    p.total_move_pct += horizon_move
                elif horizon_move < -0.1:
                    p.misses += 1

            if past.funding > 0.0008:
                p = self._pat("high_funding_fade")
                if horizon_move < 0:
                    p.hits += 1
                    p.total_move_pct += abs(horizon_move)
                elif horizon_move > 0.2:
                    p.misses += 1

            if past.crisis >= 2:
                p = self._pat("crisis_risk_off")
                if horizon_move < -0.2:
                    p.hits += 1
                elif horizon_move > 0.2:
                    p.misses += 1

        if self.last_regime and self.last_regime != sample.regime and sample.regime != "unknown":
            key = f"{self.last_regime}->{sample.regime}"
            rg = self._reg(key)
            if len(self.history) >= 2:
                prev = self.history[-2]
                if prev.price and sample.price:
                    tr_move = (sample.price - prev.price) / prev.price * 100
                    if tr_move > 0.1:
                        rg.hits += 1
                        rg.total_move_pct += tr_move
                    elif tr_move < -0.1:
                        rg.misses += 1
                    if rg.samples <= 3 or self.updates % 45 == 0:
                        new_lessons.append(
                            f"{self.symbol}: rejim {self.last_regime}→{sample.regime} "
                            f"{'+' if tr_move > 0 else '-'}{abs(tr_move):.2f}% (n={rg.samples})"
                        )

        self.last_regime = sample.regime
        self.last_price = sample.price
        return new_lessons

    def build_profile(self) -> dict:
        drivers: list[dict] = []
        for name, st in sorted(
            self.patterns.items(),
            key=lambda x: (x[1].win_rate, x[1].samples),
            reverse=True,
        ):
            if st.samples < 5:
                continue
            wr = st.win_rate
            if "bounce" in name or "pressure_up" in name or "win" in name:
                effect = "long_edge"
            elif "drop" in name or "fade" in name or "risk_off" in name or "loss" in name:
                effect = "short_edge"
            else:
                effect = "neutral"
            drivers.append({
                "factor": name,
                "label": FACTOR_LABELS.get(name, name),
                "effect": effect,
                "win_rate": round(wr, 3),
                "avg_move_pct": round(st.avg_move_pct, 3),
                "samples": st.samples,
            })

        regime_notes = []
        for key, st in sorted(
            self.regime_transitions.items(),
            key=lambda x: x[1].samples,
            reverse=True,
        ):
            if st.samples < 2:
                continue
            regime_notes.append({
                "transition": key,
                "up_bias": round(st.win_rate, 3),
                "avg_move_pct": round(st.avg_move_pct, 3),
                "samples": st.samples,
            })

        fp = self._fingerprint()
        entry_hints: list[str] = []
        avoid_hints: list[str] = []

        for d in drivers[:4]:
            label = d["label"]
            wr_pct = d["win_rate"] * 100
            if d["effect"] == "long_edge" and d["win_rate"] >= 0.52:
                entry_hints.append(f"{label} (WR {wr_pct:.0f}%, n={d['samples']})")
            elif d["effect"] == "short_edge" and d["win_rate"] >= 0.52:
                avoid_hints.append(f"Long açma: {label} short edge %{wr_pct:.0f}")

        if fp:
            rsi_a = fp.get("rsi_avg", 50)
            fund = fp.get("funding_avg", 0)
            vol = fp.get("volume_ratio_avg", 1)
            if rsi_a < 38 and not any("RSI" in h for h in entry_hints):
                entry_hints.append(f"{self.symbol} düşük RSI ort. ({rsi_a}) — mean-reversion potansiyeli")
            if rsi_a > 62 and not any("RSI" in h for h in avoid_hints):
                avoid_hints.append(f"{self.symbol} yüksek RSI ort. ({rsi_a}) — long chase riski")
            if fund > 0.0006:
                avoid_hints.append(f"Funding ort. {fund*100:.3f}% — crowded long riski")
            if vol > 1.8 and len(entry_hints) < 2:
                entry_hints.append(f"Hacim patlaması ({vol}x) — momentum takibi")
            if self.last_drift in ("DRIFTING", "SHOCK"):
                avoid_hints.append(f"Drift={self.last_drift} — model güveni düşük")

        stage = _learning_stage(self.updates, len(drivers))
        depth = _depth_score(drivers, self.updates)

        best_entry = " · ".join(entry_hints[:2]) if entry_hints else (
            f"Gözlem devam ({self.updates} tick) — henüz %{52} üstü edge yok"
        )
        avoid = " · ".join(avoid_hints[:2]) if avoid_hints else (
            f"Kriz≥2 veya {self.last_drift} iken agresif boyut yok"
        )

        return {
            "symbol": self.symbol,
            "updates": self.updates,
            "samples_in_memory": len(self.history),
            "current_regime": self.last_regime,
            "last_price": self.last_price,
            "last_drift": self.last_drift,
            "learning_stage": stage,
            "depth_score": depth,
            "fingerprint": fp,
            "drivers": drivers,
            "regime_transitions": regime_notes[:6],
            "best_entry_hint": best_entry,
            "avoid_hint": avoid,
            "updated_at": time.time(),
            "llm_enrich_count": self.llm_enrich_count,
        }
