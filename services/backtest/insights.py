"""Regime / direction lessons from backtest — fed to AI via trade:lessons Redis keys."""

from __future__ import annotations


def build_symbol_insights(result: dict) -> dict:
    if not result or result.get("total_trades", 0) < 5:
        return {}

    symbol = result["symbol"]
    monthly = result.get("monthly_returns") or []
    best = max(monthly, key=lambda m: m.get("return_pct", 0), default=None)
    worst = min(monthly, key=lambda m: m.get("return_pct", 0), default=None)

    long_wr = float(result.get("long_win_rate_pct", 0))
    short_wr = float(result.get("short_win_rate_pct", 0))
    if long_wr > short_wr + 8:
        direction_bias = "long"
        direction_lesson = f"{symbol}: Long işlemler daha başarılı (L-WR {long_wr:.0f}% vs S {short_wr:.0f}%)"
    elif short_wr > long_wr + 8:
        direction_bias = "short"
        direction_lesson = f"{symbol}: Short işlemler daha başarılı (S-WR {short_wr:.0f}% vs L {long_wr:.0f}%)"
    else:
        direction_bias = "neutral"
        direction_lesson = f"{symbol}: Long/Short dengeli — rejime göre seç"

    sharpe = float(result.get("sharpe_ratio", 0))
    dd = float(result.get("max_drawdown_pct", 0))
    ret = float(result.get("total_return_pct", 0))

    if sharpe >= 1.5 and ret > 0:
        regime_note = "trend/risk-on ortamında güçlü performans"
    elif dd > 15:
        regime_note = "yüksek drawdown — volatil/risk-off dönemlerde pozisyon küçült"
    else:
        regime_note = "karışık rejim — confidence eşiğini yükselt"

    buy_hint = "RSI<35 + MACD pozitif aylarda long tercih" if direction_bias == "long" else (
        "RSI>65 + MACD negatif aylarda short tercih" if direction_bias == "short"
        else "BB uçları + hacim onayı ile yön seç"
    )

    return {
        "symbol": symbol,
        "direction_bias": direction_bias,
        "direction_lesson": direction_lesson,
        "regime_note": regime_note,
        "best_month": best.get("month") if best else None,
        "best_month_return_pct": best.get("return_pct") if best else None,
        "worst_month": worst.get("month") if worst else None,
        "worst_month_return_pct": worst.get("return_pct") if worst else None,
        "buy_hint": buy_hint,
        "sell_hint": f"ATR stop veya TP — ort. tutma {float(result.get('avg_bars_held', 0)):.0f}h",
        "sharpe": sharpe,
        "win_rate_pct": result.get("win_rate_pct"),
        "total_return_pct": ret,
        "max_drawdown_pct": dd,
        "total_trades": result.get("total_trades"),
    }


def insight_to_lesson_line(insights: dict) -> str:
    if not insights:
        return ""
    parts = [
        insights.get("direction_lesson", ""),
        insights.get("regime_note", ""),
        f"Al: {insights.get('buy_hint', '')}",
        f"Sat: {insights.get('sell_hint', '')}",
    ]
    return " | ".join(p for p in parts if p)
