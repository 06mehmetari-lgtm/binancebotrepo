"""
Core backtesting engine.
Uses strict multi-confirmation signal logic to reduce overtrading.

Exit strategy: 2.0x ATR stop-loss, 3.5x ATR take-profit (R:R ≈ 1:1.75)
Fees: 0.05% taker × 2 = 0.10% round trip.
Cooldown: 12-bar wait after any exit before re-entering same symbol.
"""
import logging
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

TAKER_FEE = 0.0005
ROUND_TRIP = TAKER_FEE * 2


class BacktestEngine:
    def __init__(
        self,
        initial_capital: float = 10_000,
        position_pct: float = 0.05,
        max_positions: int = 3,
        atr_sl_mult: float = 2.0,        # wider stop — avoids noise exits
        atr_tp_mult: float = 3.5,        # better R:R (1:1.75)
        max_hold_bars: int = 72,          # 72h max hold
        confidence_threshold: float = 0.72,  # strict filter
        min_margin: float = 0.10,         # long score must beat short score by ≥10%
        cooldown_bars: int = 12,          # 12h wait after any exit
    ):
        self.initial_capital = initial_capital
        self.position_pct = position_pct
        self.max_positions = max_positions
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp_mult = atr_tp_mult
        self.max_hold_bars = max_hold_bars
        self.confidence_threshold = confidence_threshold
        self.min_margin = min_margin
        self.cooldown_bars = cooldown_bars

    def _build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        # RSI(14) — Wilder's smoothing
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(com=13, adjust=False).mean()
        avg_loss = loss.ewm(com=13, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi"] = 100 - 100 / (1 + rs)

        # MACD(12,26,9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        macd_sig = macd_line.ewm(span=9, adjust=False).mean()
        df["macd_hist"] = macd_line - macd_sig
        df["macd_delta"] = df["macd_hist"].diff()  # histogram direction

        # ATR(14)
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.ewm(com=13, adjust=False).mean()

        # ATR as % of price (normalised volatility)
        df["atr_pct"] = df["atr"] / close

        # Bollinger Bands(20, 2σ)
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        df["bb_pos"] = (close - bb_lower) / (bb_upper - bb_lower).replace(0, np.nan)

        # EMAs
        df["ema20"] = close.ewm(span=20, adjust=False).mean()
        df["ema50"] = close.ewm(span=50, adjust=False).mean()
        df["ema200"] = close.ewm(span=200, adjust=False).mean()

        # ADX(14) — simplified
        dm_p = (high - high.shift(1)).clip(lower=0)
        dm_m = (low.shift(1) - low).clip(lower=0)
        dm_p = dm_p.where(dm_p > dm_m, 0)
        dm_m = dm_m.where(dm_m > dm_p, 0)
        di_p = 100 * dm_p.ewm(com=13, adjust=False).mean() / df["atr"].replace(0, np.nan)
        di_m = 100 * dm_m.ewm(com=13, adjust=False).mean() / df["atr"].replace(0, np.nan)
        dx = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)
        df["adx"] = dx.ewm(com=13, adjust=False).mean()

        # Stochastic %K(14) and direction
        low14 = low.rolling(14).min()
        high14 = high.rolling(14).max()
        df["stoch_k"] = 100 * (close - low14) / (high14 - low14).replace(0, np.nan)
        df["stoch_delta"] = df["stoch_k"].diff()

        # Volume ratio (vs 20-bar MA)
        df["vol_ratio"] = volume / volume.rolling(20).mean().replace(0, np.nan)

        # 2-bar and 5-bar momentum
        df["mom2"] = close.pct_change(2)
        df["mom5"] = close.pct_change(5)

        return df

    def _score_long(self, r: dict) -> float:
        """
        Score [0..1] for LONG entry. Requires multiple confirming factors.
        Target: fewer but higher-quality signals.
        """
        score = 0.0
        rsi      = r.get("rsi", 50) or 50
        macd     = r.get("macd_hist", 0) or 0
        m_delta  = r.get("macd_delta", 0) or 0
        bb       = r.get("bb_pos", 0.5) or 0.5
        adx      = r.get("adx", 20) or 20
        ema20    = r.get("ema20", 0) or 0
        ema50    = r.get("ema50", 0) or 0
        ema200   = r.get("ema200", 0) or 0
        close    = r.get("close", 0) or 0
        vol      = r.get("vol_ratio", 1) or 1
        stoch    = r.get("stoch_k", 50) or 50
        s_delta  = r.get("stoch_delta", 0) or 0
        mom2     = r.get("mom2", 0) or 0
        mom5     = r.get("mom5", 0) or 0

        # ── RSI — strong oversold required ──────────────────────────────────
        if rsi < 28:    score += 0.25
        elif rsi < 35:  score += 0.12
        # No points for RSI > 35 (neutral or overbought is not a long signal)

        # ── MACD — must be turning UP (histogram crossing or accelerating) ──
        if macd > 0 and m_delta > 0:    score += 0.22  # positive and increasing
        elif macd < 0 and m_delta > 0:  score += 0.10  # negative but turning up (early reversal)

        # ── Bollinger — price compressed near lower band ─────────────────────
        if bb < 0.10:    score += 0.22  # extreme lower band
        elif bb < 0.20:  score += 0.12
        elif bb < 0.30:  score += 0.04

        # ── EMA trend alignment ───────────────────────────────────────────────
        full_bullish = (ema20 > 0 and ema50 > 0 and ema200 > 0
                        and ema20 > ema50 and ema50 > ema200)
        if full_bullish:
            score += 0.15
        elif ema20 > 0 and ema50 > 0 and ema20 > ema50:
            score += 0.07

        if close > 0 and ema200 > 0 and close > ema200:
            score += 0.06

        # ── Stochastic — oversold and turning up ─────────────────────────────
        if stoch < 15 and s_delta > 0:   score += 0.14
        elif stoch < 25:                  score += 0.06

        # ── Volume surge — confirms the move ─────────────────────────────────
        if vol > 2.0:    score += 0.10
        elif vol > 1.5:  score += 0.05

        # ── Momentum confirmation ─────────────────────────────────────────────
        if mom2 > 0 and mom5 < 0:  score += 0.04  # short-term bounce in downtrend
        elif mom2 > 0:             score += 0.02

        # ── ADX filter — penalise choppy / reward trending ───────────────────
        if adx < 20:    score *= 0.40   # strong penalty for ranging market
        elif adx > 30:  score *= 1.18   # clear trend confirmation

        return min(float(score), 1.0)

    def _score_short(self, r: dict) -> float:
        """Score [0..1] for SHORT entry. Mirror of _score_long."""
        score = 0.0
        rsi      = r.get("rsi", 50) or 50
        macd     = r.get("macd_hist", 0) or 0
        m_delta  = r.get("macd_delta", 0) or 0
        bb       = r.get("bb_pos", 0.5) or 0.5
        adx      = r.get("adx", 20) or 20
        ema20    = r.get("ema20", 0) or 0
        ema50    = r.get("ema50", 0) or 0
        ema200   = r.get("ema200", 0) or 0
        close    = r.get("close", 0) or 0
        vol      = r.get("vol_ratio", 1) or 1
        stoch    = r.get("stoch_k", 50) or 50
        s_delta  = r.get("stoch_delta", 0) or 0
        mom2     = r.get("mom2", 0) or 0
        mom5     = r.get("mom5", 0) or 0

        if rsi > 72:    score += 0.25
        elif rsi > 65:  score += 0.12

        if macd < 0 and m_delta < 0:    score += 0.22
        elif macd > 0 and m_delta < 0:  score += 0.10

        if bb > 0.90:    score += 0.22
        elif bb > 0.80:  score += 0.12
        elif bb > 0.70:  score += 0.04

        full_bearish = (ema20 > 0 and ema50 > 0 and ema200 > 0
                        and ema20 < ema50 and ema50 < ema200)
        if full_bearish:
            score += 0.15
        elif ema20 > 0 and ema50 > 0 and ema20 < ema50:
            score += 0.07

        if close > 0 and ema200 > 0 and close < ema200:
            score += 0.06

        if stoch > 85 and s_delta < 0:   score += 0.14
        elif stoch > 75:                  score += 0.06

        if vol > 2.0:    score += 0.10
        elif vol > 1.5:  score += 0.05

        if mom2 < 0 and mom5 > 0:  score += 0.04
        elif mom2 < 0:             score += 0.02

        if adx < 20:    score *= 0.40
        elif adx > 30:  score *= 1.18

        return min(float(score), 1.0)

    def run(self, symbol: str, klines: list) -> dict:
        if len(klines) < 250:
            return {}

        cols = ["open_time", "open", "high", "low", "close", "volume",
                "close_time", "qvol", "ntrades", "tbbase", "tbquote", "ignore"]
        df = pd.DataFrame(klines, columns=cols)
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df.set_index("ts").sort_index()

        df = self._build_features(df)
        required = ["rsi", "macd_hist", "macd_delta", "atr", "adx",
                    "bb_pos", "ema200", "vol_ratio", "stoch_k"]
        df = df.dropna(subset=required)

        if len(df) < 100:
            return {}

        rows = df.reset_index()
        n = len(rows)

        capital = self.initial_capital
        equity: list[float] = [capital]
        monthly_equity: dict[str, float] = {}
        trades: list[dict] = []
        open_pos: list[dict] = []
        last_exit_bar: int = -999  # cooldown tracking

        for i in range(1, n - 1):
            row = rows.iloc[i]
            rd = row.to_dict()
            next_open = float(rows.iloc[i + 1]["open"])

            # ── Close existing positions ───────────────────────────────────
            still_open: list[dict] = []
            for pos in open_pos:
                entry = pos["entry"]
                atr = pos["atr"]
                direction = pos["direction"]
                bar_age = i - pos["bar"]

                if direction == "long":
                    sl = entry - self.atr_sl_mult * atr
                    tp = entry + self.atr_tp_mult * atr
                    if float(rd["low"]) <= sl:
                        exit_p, reason = sl, "stop_loss"
                    elif float(rd["high"]) >= tp:
                        exit_p, reason = tp, "take_profit"
                    elif bar_age >= self.max_hold_bars:
                        exit_p, reason = float(rd["close"]), "time_exit"
                    else:
                        still_open.append(pos)
                        continue
                    raw_pnl = (exit_p - entry) / entry
                else:
                    sl = entry + self.atr_sl_mult * atr
                    tp = entry - self.atr_tp_mult * atr
                    if float(rd["high"]) >= sl:
                        exit_p, reason = sl, "stop_loss"
                    elif float(rd["low"]) <= tp:
                        exit_p, reason = tp, "take_profit"
                    elif bar_age >= self.max_hold_bars:
                        exit_p, reason = float(rd["close"]), "time_exit"
                    else:
                        still_open.append(pos)
                        continue
                    raw_pnl = (entry - exit_p) / entry

                net_pnl = raw_pnl - ROUND_TRIP
                capital *= (1 + net_pnl * pos["size_pct"])
                last_exit_bar = i
                trades.append({
                    "direction": direction,
                    "entry": round(entry, 6),
                    "exit": round(exit_p, 6),
                    "pnl_pct": round(net_pnl * 100, 4),
                    "exit_reason": reason,
                    "bars_held": bar_age,
                    "entry_time": str(pos["ts"])[:16],
                    "confidence": round(pos["confidence"], 3),
                })

            open_pos = still_open
            equity.append(capital)

            month_key = str(row["ts"])[:7]
            monthly_equity[month_key] = capital

            # ── Cooldown check ─────────────────────────────────────────────
            if i - last_exit_bar < self.cooldown_bars:
                continue

            # ── Open new positions ─────────────────────────────────────────
            if len(open_pos) >= self.max_positions:
                continue

            l_score = self._score_long(rd)
            s_score = self._score_short(rd)

            direction = None
            confidence = 0.0

            if (l_score >= self.confidence_threshold
                    and l_score > s_score + self.min_margin):
                direction, confidence = "long", l_score
            elif (s_score >= self.confidence_threshold
                    and s_score > l_score + self.min_margin):
                direction, confidence = "short", s_score

            if direction is None:
                continue

            open_pos.append({
                "direction": direction,
                "entry": next_open,
                "atr": float(rd["atr"]),
                "bar": i,
                "ts": str(row["ts"])[:16],
                "size_pct": self.position_pct,
                "confidence": confidence,
            })

        # ── Force-close remaining positions at last price ──────────────────
        last_close = float(rows.iloc[-1]["close"])
        for pos in open_pos:
            entry = pos["entry"]
            if pos["direction"] == "long":
                raw_pnl = (last_close - entry) / entry
            else:
                raw_pnl = (entry - last_close) / entry
            net_pnl = raw_pnl - ROUND_TRIP
            capital *= (1 + net_pnl * pos["size_pct"])
            trades.append({
                "direction": pos["direction"],
                "entry": round(entry, 6),
                "exit": round(last_close, 6),
                "pnl_pct": round(net_pnl * 100, 4),
                "exit_reason": "end_of_backtest",
                "bars_held": n - 1 - pos["bar"],
                "entry_time": pos["ts"],
                "confidence": round(pos["confidence"], 3),
            })

        if not trades:
            return {}

        return self._calculate_metrics(symbol, trades, equity, monthly_equity)

    def run_walk_forward(
        self,
        symbol: str,
        klines: list,
        *,
        train_ratio: float = 0.7,
        n_folds: int = 3,
    ) -> dict:
        """
        Walk-forward validation — train params implicit in engine; test on OOS slices.
        Avoids single-period overfit (no future leakage within each fold).
        """
        if len(klines) < 400:
            return self.run(symbol, klines)

        fold_results: list[dict] = []
        n = len(klines)
        fold_size = max(200, n // max(n_folds, 1))

        for fold in range(n_folds):
            start = fold * fold_size
            end = min(n, start + fold_size)
            if end - start < 250:
                continue
            slice_kl = klines[start:end]
            split = int(len(slice_kl) * train_ratio)
            test_kl = slice_kl[split:]
            if len(test_kl) < 120:
                continue
            res = self.run(symbol, test_kl)
            if res and res.get("total_trades", 0) >= 3:
                res["fold"] = fold + 1
                res["oos_bars"] = len(test_kl)
                fold_results.append(res)

        if not fold_results:
            return self.run(symbol, klines)

        avg_wr = float(np.mean([r["win_rate"] for r in fold_results]))
        avg_sharpe = float(np.mean([r["sharpe_ratio"] for r in fold_results]))
        avg_ret = float(np.mean([r["total_return_pct"] for r in fold_results]))
        avg_dd = float(np.mean([r["max_drawdown_pct"] for r in fold_results]))
        total_trades = sum(r["total_trades"] for r in fold_results)

        base = dict(fold_results[-1])
        base.update({
            "symbol": symbol,
            "walk_forward": True,
            "folds": len(fold_results),
            "total_trades": total_trades,
            "win_rate": round(avg_wr, 4),
            "win_rate_pct": round(avg_wr * 100, 2),
            "sharpe_ratio": round(avg_sharpe, 3),
            "total_return_pct": round(avg_ret, 2),
            "max_drawdown_pct": round(avg_dd, 2),
            "fold_results": [
                {
                    "fold": r.get("fold"),
                    "win_rate_pct": r.get("win_rate_pct"),
                    "sharpe_ratio": r.get("sharpe_ratio"),
                    "total_trades": r.get("total_trades"),
                }
                for r in fold_results
            ],
        })
        return base

    def _calculate_metrics(
        self,
        symbol: str,
        trades: list[dict],
        equity: list[float],
        monthly_equity: dict[str, float],
    ) -> dict:
        wins = [t for t in trades if t["pnl_pct"] > 0]
        losses = [t for t in trades if t["pnl_pct"] <= 0]
        longs = [t for t in trades if t["direction"] == "long"]
        shorts = [t for t in trades if t["direction"] == "short"]

        win_rate = len(wins) / len(trades)
        avg_win = float(np.mean([t["pnl_pct"] for t in wins])) if wins else 0.0
        avg_loss = float(np.mean([t["pnl_pct"] for t in losses])) if losses else 0.0
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

        eq = np.array(equity, dtype=float)
        returns = np.diff(eq) / eq[:-1]
        annual_factor = np.sqrt(24 * 365)
        sharpe = float(np.mean(returns) / (np.std(returns) + 1e-10)) * annual_factor

        peak = np.maximum.accumulate(eq)
        drawdown = (eq - peak) / peak
        max_dd = float(abs(drawdown.min()))

        total_return = (equity[-1] / self.initial_capital - 1) * 100

        exit_reasons: dict[str, int] = {}
        for t in trades:
            r = t.get("exit_reason", "other")
            exit_reasons[r] = exit_reasons.get(r, 0) + 1

        months = sorted(monthly_equity.keys())
        monthly_returns: list[dict] = []
        prev_val = self.initial_capital
        for m in months:
            val = monthly_equity[m]
            ret = (val - prev_val) / prev_val * 100
            monthly_returns.append({"month": m, "return_pct": round(ret, 2), "capital": round(val, 2)})
            prev_val = val

        return {
            "symbol": symbol,
            "total_trades": len(trades),
            "win_rate": round(win_rate, 4),
            "win_rate_pct": round(win_rate * 100, 2),
            "avg_win_pct": round(avg_win, 3),
            "avg_loss_pct": round(avg_loss, 3),
            "profit_factor": round(profit_factor, 3),
            "total_return_pct": round(total_return, 2),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "final_capital": round(equity[-1], 2),
            "long_trades": len(longs),
            "short_trades": len(shorts),
            "long_win_rate_pct": round(
                len([t for t in longs if t["pnl_pct"] > 0]) / len(longs) * 100 if longs else 0, 1
            ),
            "short_win_rate_pct": round(
                len([t for t in shorts if t["pnl_pct"] > 0]) / len(shorts) * 100 if shorts else 0, 1
            ),
            "avg_bars_held": round(float(np.mean([t["bars_held"] for t in trades])), 1),
            "exit_reasons": exit_reasons,
            "monthly_returns": monthly_returns,
        }
