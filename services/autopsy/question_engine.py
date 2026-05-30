"""60-question post-trade autopsy engine."""

AUTOPSY_QUESTIONS = [
    # BLOK A: SİNYAL KALİTESİ (1-15)
    "Was the entry signal confirmed by multiple timeframes?",
    "Was the confidence score above 0.65 at entry?",
    "Did all 3+ agents agree on the direction?",
    "Was the funding rate aligned with the trade direction?",
    "Was open interest increasing at entry?",
    "Was the L/S ratio supportive (contrarian signal)?",
    "Was the order book imbalance > 0.2 in trade direction?",
    "Was the MACD histogram positive for longs / negative for shorts?",
    "Was RSI in a reasonable range (not overbought/oversold against direction)?",
    "Was the Bollinger Band position favorable?",
    "Was the ADX above 20 (confirming a trend)?",
    "Was the stochastic momentum aligned with the signal?",
    "Was the news sentiment score > 0.1 for longs / < -0.1 for shorts?",
    "Was the Fear & Greed index in a contrarian-favorable zone?",
    "Was the macro environment (VIX < 30) supportive?",

    # BLOK B: ZAMANLAMA (16-25)
    "Was the entry taken within 5 minutes of the signal?",
    "Was the exit taken before the position reversed more than 1%?",
    "Was the trade held long enough (> 30 minutes) to realize the move?",
    "Was the trade closed before hitting the daily loss limit?",
    "Was the entry during high-liquidity hours (08:00-20:00 UTC)?",
    "Was the exit at a significant support/resistance level?",
    "Was the position sized down during drift WARNING status?",
    "Was position size = 0 during drift SHOCK status?",
    "Was the hold duration appropriate for the regime (trend vs. range)?",
    "Was the trade avoided during extreme funding rate (> 0.3%)?",

    # BLOK C: BAĞLAM (26-40)
    "Was the market regime correctly identified at entry?",
    "Was a crisis event (level >= 2) active at entry?",
    "Was drift status STABLE at the time of entry?",
    "Was BTC dominance trend aligned with the altcoin trade?",
    "Was the VIX below the danger threshold (40)?",
    "Were there large liquidations (> $50K) in the 5 minutes before entry?",
    "Was the spread below 0.1% at the time of entry?",
    "Was the on-chain exchange netflow positive for longs?",
    "Was the Reddit sentiment score aligned?",
    "Was the FRED yield curve (T10Y2Y) in a non-inverted state?",
    "Was the DXY trending in a favorable direction?",
    "Was BTC's momentum positive for longs at entry?",
    "Was the scenario engine clear (no crisis simulation active)?",
    "Was the shadow system Sharpe > 1.0 before this trade?",
    "Was the NEAT best genome fitness > 1.0?",

    # BLOK D: RİSK YÖNETİMİ (41-50)
    "Was position size within Kelly criteria?",
    "Was position size <= 5% of portfolio?",
    "Was leverage <= 3x?",
    "Was the daily loss budget > 0.5% remaining at entry?",
    "Was the trade the only open position (not exceeding 3)?",
    "Was a stop-loss level mentally set before entry?",
    "Was the risk/reward ratio >= 1.5:1?",
    "Was the immunity system approval received?",
    "Was the portfolio heat (total exposure) < 15%?",
    "Was DRY_RUN=false confirmed before live execution?",

    # BLOK E: ÇIKIŞ & ÖĞRENME (51-60)
    "Was the exit triggered by a reversal signal (not panic)?",
    "Was the exit confirmed by at least 2 agents voting opposite?",
    "Did the autopsy identify the correct error category?",
    "Was the genome penalized if the error was REGIME_MISMATCH?",
    "Was the memory written to Qdrant successfully?",
    "Did similar past trades (RAG retrieval) show the same error pattern?",
    "Was the agent weight updated based on this outcome?",
    "Was the trade result recorded in the trades table?",
    "Was the shadow system performance updated after this trade?",
    "Was the daily PnL updated in Redis after close?",
]


class QuestionEngine:
    def run(self, trade_analysis: dict, context: dict) -> list[dict]:
        results = []
        for i, question in enumerate(AUTOPSY_QUESTIONS, 1):
            answer = self._auto_answer(i, question, trade_analysis, context)
            results.append({
                "q_num": i,
                "question": question,
                "answer": answer,
                "trade_id": trade_analysis.get("trade_id"),
            })
        return results

    def _auto_answer(self, q_num: int, question: str, analysis: dict, ctx: dict) -> str:
        """Auto-answer questions where data is available."""
        pnl = float(analysis.get("pnl_pct", 0))
        conf = float(analysis.get("confidence", 0))
        crisis = int(ctx.get("crisis_level", 0))
        drift = ctx.get("drift_status", "STABLE")
        hold_h = float(analysis.get("hold_hours", 1))

        if q_num == 2:
            return "YES" if conf > 0.65 else "NO"
        if q_num == 7:
            return "UNKNOWN"
        if q_num == 21:
            return "YES" if crisis < 2 else "NO"
        if q_num == 27:
            return "NO" if crisis >= 2 else "YES"
        if q_num == 28:
            return "YES" if drift == "STABLE" else f"NO ({drift})"
        if q_num == 41:
            return "YES" if conf <= 0.05 else "UNKNOWN"
        if q_num == 44:
            return "UNKNOWN"
        return "UNKNOWN"
