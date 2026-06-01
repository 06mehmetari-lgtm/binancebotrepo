"""
Bear Agent — argues the bearish case using Claude API.
Returns structured dict with signal, confidence, reasoning.
"""
import json
import logging
import os

import anthropic

MODEL = "claude-sonnet-4-6"
log = logging.getLogger(__name__)


class BearAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        self.role = "You are a bearish crypto trading analyst. Argue the short/sell case using ALL available evidence."

    def analyze(self, context: dict) -> dict:
        symbol   = context.get("symbol", "CRYPTO")
        regime   = context.get("regime", "unknown")
        rsi      = context.get("rsi_14", "N/A")
        macd     = context.get("macd_hist", "N/A")
        cvd      = context.get("cvd_5m", "N/A")
        funding  = context.get("funding_rate", "N/A")
        fear_g   = context.get("fear_greed", "N/A")
        ml_score = context.get("ml_score", "N/A")
        crisis   = context.get("crisis_level", 0)

        prompt = f"""You are a bearish crypto trading analyst. Argue the short/sell case.

Asset: {symbol} | Regime: {regime} | Crisis Level: {crisis}
Technical: RSI={rsi}, MACD_hist={macd}
On-chain: CVD_5m={cvd}, Funding={funding}
Sentiment: Fear&Greed={fear_g}
ML Score: {ml_score}

Provide your BEARISH analysis. Be direct. Respond ONLY with valid JSON (no markdown):
{{
  "signal": "short" or "flat",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<1-2 sentences explaining why bearish>"
}}"""

        try:
            resp = self.client.messages.create(
                model=MODEL,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = json.loads(raw)
            return {
                "agent":      "bear_agent",
                "signal":     str(parsed.get("signal", "flat")),
                "direction":  str(parsed.get("signal", "flat")),
                "confidence": float(parsed.get("confidence", 0.5)),
                "reasoning":  str(parsed.get("reasoning", "")),
            }
        except Exception as e:
            log.warning(f"BearAgent LLM parse error: {e}")
            return {"agent": "bear_agent", "signal": "flat", "direction": "flat",
                    "confidence": 0.5, "reasoning": "LLM unavailable"}
