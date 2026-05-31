"""
Core backtesting engine.
Uses the same signal logic as signal_generator.py (technical fallback).
Exit strategy: ATR-based stop-loss + take-profit, max hold 48 bars.
Fees: 0.05% taker × 2 = 0.10% round trip.
"""
import logging
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

TAKER_FEE = 0.0005       # 0.05% per side (Binance taker)
ROUND_TRIP = TAKER_FEE * 2   # 0.10% total cost per trade


class BacktestEngine:
    def __init__(
        self,
        initial_capital: float = 10_000,
        position_pct: float = 0.05,      # 5% per trade (immunity limit)
        max_positions: int = 3,           # immunity: max 3 concurrent
        atr_sl_mult: float = 1.5,         # stop loss = 1.5 × ATR
        atr_tp_mult: float = 2.5,         # take profit = 2.5 × ATR  (1.67 R:R)
        max_hold_bars: int = 48,          # time-exit after 48h
        confidence_threshold: float = 0.60,
    ):
        self.initial_capital = initial_capital
        self.position_pct = position_pct
        self.max_positions = max_positions
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp_mult = atr_tp_mult
        self.max_hold_bars = max_hold_bars
        self.confidence_threshold = confidence_threshold

    # ──────────────────────────────────────────────────────────────────────────
    # Feature computation
    # ──────────────────────────────────────────────────────────────────────────

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

        # ATR(14)
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.ewm(com=13, adjust=False).mean()

        # Bollinger Bands (20,2)
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
        dx = (100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan))
        df["adx"] = dx.ewm(com=13, adjust=False).mean()

        # Stochastic %K(14)
        low14 = low.rolling(14).min()
        high14 = high.rolling(14).max()
        df["stoch_k"] = 100 * (close - low14) / (high14 - low14).replace(0, np.nan)

        # Volume ratio
        df["vol_ratio"] = volume / volume.rolling(20).mean().replace(0, np.nan)

        # 2-bar momentum
        df["mom2"] = close - close.shift(2)

        return df

    # ──────────────────────────────────────────────────────────────────────────
    # Signal scoring — same philosophy as signal_generator.py technical fallback
    # ──────────────────────────────────────────────────────────────────────────

    def _score_long(self, r: dict) -> float:
        score = 0.0
        rsi = r.get("rsi", 50) or 50
        macd = r.get("macd_hist", 0) or 0
        bb = r.get("bb_pos", 0.5) or 0.5
        adx = r.get("adx", 0) or 0
        ema20 = r.get("ema20", 0) or 0
        ema50 = r.get("ema50", 0) or 0
        close = r.get("close", 0) or 0
        ema200 = r.get("ema200", 0) or 0
        vol = r.get("vol_ratio", 1) or 1
        stoch = r.get("stoch_k", 50) or 50
        mom2 = r.get("mom2", 0) or 0

        # RSI oversold
        if rsi < 28:   score += 0.22
        elif rsi < 35: score += 0.14
        elif rsi < 42: score += 0.06

        # MACD momentum turning up
        if macd > 0: score += 0.18

        # Bollinger — price near lower band
        if bb < 0.15:   score += 0.18
        elif bb < 0.25: score += 0.10
        elif bb < 0.35: score += 0.04

        # EMA trend alignment
        if ema20 > 0 and ema50 > 0 and ema20 > ema50: score += 0.12
        if close > 0 and ema200 > 0 and close > ema200: score += 0.08

        # Stochastic oversold
        if stoch < 20:   score += 0.10
        elif stoch < 35: score += 0.05

        # Volume surge
        if vol > 1.5:   score += 0.10
        elif vol > 1.2: score += 0.05

        # 2-bar momentum
        if mom2 > 0: score += 0.04

        # ADX modifier
        if adx < 15:   score *= 0.55   # choppy — penalise
        elif adx > 25: score *= 1.12   # strong trend — amplify

        return min(float(score), 1.0)

    def _score_short(self, r: dict) -> float:
        score = 0.0
        rsi = r.get("rsi", 50) or 50
        macd = r.get("macd_hist", 0) or 0
        bb = r.get("bb_pos", 0.5) or 0.5
        adx = r.get("adx", 0) or 0
        ema20 = r.get("ema20", 0) or 0
        ema50 = r.get("ema50", 0) or 0
        close = r.get("close", 0) or 0
        ema200 = r.get("ema200", 0) or 0
        vol = r.get("vol_ratio", 1) or 1
        stoch = r.get("stoch_k", 50) or 50
        mom2 = r.get("mom2", 0) or 0

        if rsi > 72:   score += 0.22
        elif rsi > 65: score += 0.14
        elif rsi > 58: score += 0.06

        if macd < 0: score += 0.18

        if bb > 0.85:   score += 0.18
        elif bb > 0.75: score += 0.10
        elif bb > 0.65: score += 0.04

        if ema20 > 0 and ema50 > 0 and ema20 < ema50: score += 0.12
        if close > 0 and ema200 > 0 and close < ema200: score += 0.08

        if stoch > 80:   score += 0.10
        elif stoch > 65: score += 0.05

        if vol > 1.5:   score += 0.10
        elif vol > 1.2: score += 0.05

        if mom2 < 0: score += 0.04

        if adx < 15:   score *= 0.55
        elif adx > 25: score *= 1.12

        return min(float(score), 1.0)

    # ──────────────────────────────────────────────────────────────────────────
    # Trade simulation
    # ──────────────────────────────────────────────────────────────────────────

    def run(self, symbol: str, klines: list) -> dict:
        if len(klines) < 250:
            log.warning(f"[{symbol}] Only {len(klines)} bars — skipping")
            return {}

        cols = ["open_time", "open", "high", "low", "close", "volume",
                "close_time", "qvol", "ntrades", "tbbase", "tbquote", "ignore"]
        df = pd.DataFrame(klines, columns=cols)
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df.set_index("ts").sort_index()

        df = self._build_features(df)
        required = ["rsi", "macd_hist", "atr", "adx", "bb_pos", "ema200", "vol_ratio"]
        df = df.dropna(subset=required)

        if len(df) < 100:
            return {}

        rows = df.reset_index()
        n = len(rows)

        capital = self.initial_capital
        equity: list[float] = [capital]
        monthly_equity: dict[str, float] = {}
        trades: list[dict] = []
        open_pos: list[dict] = []   # list of position dicts

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
                    bar_low = float(rd["low"])
                    bar_high = float(rd["high"])

                    if bar_low <= sl:
                        exit_p, reason = sl, "stop_loss"
                    elif bar_high >= tp:
                        exit_p, reason = tp, "take_profit"
                    elif bar_age >= self.max_hold_bars:
                        exit_p, reason = float(rd["close"]), "time_exit"
                    else:
                        still_open.append(pos)
                        continue
                    raw_pnl = (exit_p - entry) / entry
                else:  # short
                    sl = entry + self.atr_sl_mult * atr
                    tp = entry - self.atr_tp_mult * atr
                    bar_high = float(rd["high"])
                    bar_low = float(rd["low"])

                    if bar_high >= sl:
                        exit_p, reason = sl, "stop_loss"
                    elif bar_low <= tp:
                        exit_p, reason = tp, "take_profit"
                    elif bar_age >= self.max_hold_bars:
                        exit_p, reason = float(rd["close"]), "time_exit"
                    else:
                        still_open.append(pos)
                        continue
                    raw_pnl = (entry - exit_p) / entry

                net_pnl = raw_pnl - ROUND_TRIP
                capital *= (1 + net_pnl * pos["size_pct"])
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

            # Monthly snapshot
            month_key = str(row["ts"])[:7]
            monthly_equity[month_key] = capital

            # ── Open new positions ─────────────────────────────────────────
            if len(open_pos) >= self.max_positions:
                continue

            l_score = self._score_long(rd)
            s_score = self._score_short(rd)

            direction = None
            confidence = 0.0
            if l_score >= self.confidence_threshold and l_score > s_score:
                direction, confidence = "long", l_score
            elif s_score >= self.confidence_threshold and s_score > l_score:
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

    # ──────────────────────────────────────────────────────────────────────────
    # Metrics
    # ──────────────────────────────────────────────────────────────────────────

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

        # Monthly returns
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
            "long_win_rate_pct": round(len([t for t in longs if t["pnl_pct"] > 0]) / len(longs) * 100 if longs else 0, 1),
            "short_win_rate_pct": round(len([t for t in shorts if t["pnl_pct"] > 0]) / len(shorts) * 100 if shorts else 0, 1),
            "avg_bars_held": round(float(np.mean([t["bars_held"] for t in trades])), 1),
            "exit_reasons": exit_reasons,
            "monthly_returns": monthly_returns,
        }
