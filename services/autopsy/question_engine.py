AUTOPSY_QUESTIONS = [
    "Was the entry signal confirmed by multiple timeframes?",
    "Was the funding rate aligned with the trade direction?",
    "Was open interest increasing at entry?",
    "Was the macro environment supportive?",
    "Did the order book show directional imbalance?",
    "Was the stop loss properly placed beyond structure?",
    "Was position size within Kelly criteria?",
    "Was the trade taken during high liquidity hours?",
    "Did sentiment align with technical signal?",
    "Was the trade cut before max loss was hit?",
]

class QuestionEngine:
    def run(self, trade_analysis: dict, context: dict) -> list[dict]:
        results = []
        for q in AUTOPSY_QUESTIONS:
            results.append({"question": q, "trade_id": trade_analysis.get("trade_id"), "context": context})
        return results
