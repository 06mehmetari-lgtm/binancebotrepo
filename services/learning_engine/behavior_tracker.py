"""
Per-symbol continual learning — observes feature/context/ticker streams,
builds behavioral profiles (regime reactions, drivers, entry/exit hints).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


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


@dataclass
class SymbolLearner:
    symbol: str
    history: deque = field(default_factory=lambda: deque(maxlen=180))
    patterns: dict[str, PatternStats] = field(default_factory=dict)
    regime_transitions: dict[str, PatternStats] = field(default_factory=dict)
    last_regime: str = "unknown"
    last_price: float = 0.0
    updates: int = 0

    def _pat(self, key: str) -> PatternStats:
        if key not in self.patterns:
            self.patterns[key] = PatternStats()
        return self.patterns[key]

    def _reg(self, key: str) -> PatternStats:
        if key not in self.regime_transitions:
            self.regime_transitions[key] = PatternStats()
        return self.regime_transitions[key]

    def observe(self, sample: TickSample) -> list[str]:
        """Returns new lesson lines when something meaningful was learned."""
        new_lessons: list[str] = []
        self.history.append(sample)
        self.updates += 1

        if self.last_price > 0 and sample.price > 0:
            move_pct = (sample.price - self.last_price) / self.last_price * 100
        else:
            move_pct = 0.0

        # Evaluate pending hypotheses from previous ticks (3-step horizon)
        if len(self.history) >= 4:
            past = self.history[-4]
            mid = self.history[-2]
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

        # Regime transition learning
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
                    new_lessons.append(
                        f"Rejim {self.last_regime}→{sample.regime}: "
                        f"{'yükseliş' if tr_move > 0 else 'düşüş'} eğilimi %{abs(tr_move):.2f}"
                    )

        self.last_regime = sample.regime
        self.last_price = sample.price
        return new_lessons

    def build_profile(self) -> dict:
        drivers: list[dict] = []
        for name, st in sorted(
            self.patterns.items(),
            key=lambda x: x[1].samples,
            reverse=True,
        )[:8]:
            if st.samples < 3:
                continue
            effect = "up" if "bounce" in name or "pressure_up" in name else (
                "down" if "drop" in name or "fade" in name or "risk_off" in name else "mixed"
            )
            drivers.append({
                "factor": name,
                "effect": effect,
                "win_rate": round(st.win_rate, 3),
                "avg_move_pct": round(st.avg_move_pct, 3),
                "samples": st.samples,
            })

        regime_notes = []
        for key, st in self.regime_transitions.items():
            if st.samples < 2:
                continue
            regime_notes.append({
                "transition": key,
                "up_bias": st.win_rate,
                "avg_move_pct": round(st.avg_move_pct, 3),
                "samples": st.samples,
            })

        best_entry = "RSI aşırı satış + bid imbalance + düşük funding"
        avoid = "yüksek funding + crisis≥2 + DRIFTING"
        if drivers:
            top = drivers[0]
            if top["effect"] == "up":
                best_entry = f"{top['factor']} onaylı (WR {top['win_rate']*100:.0f}%)"
            elif top["effect"] == "down":
                avoid = f"{top['factor']} aktifken long açma"

        return {
            "symbol": self.symbol,
            "updates": self.updates,
            "samples_in_memory": len(self.history),
            "current_regime": self.last_regime,
            "last_price": self.last_price,
            "drivers": drivers,
            "regime_transitions": regime_notes[:6],
            "best_entry_hint": best_entry,
            "avoid_hint": avoid,
            "updated_at": time.time(),
        }
