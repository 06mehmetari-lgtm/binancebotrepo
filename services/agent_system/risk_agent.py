"""
Risk Agent — evaluates VaR, Kelly fraction, drawdown risk using Claude API.
Returns flat signal when risk is elevated; biases toward caution.
"""
import json
import logging
import os

import anthropic

MODEL = "claude-sonnet-4-6"
log = logging.getLogger(__name__)


class RiskAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    def analyze(self, context: dict) -> dict:
        symbol      = context.get("symbol", "CRYPTO")
        crisis      = int(context.get("crisis_level", 0))
        vix         = context.get("vix_level", "N/A")
        funding     = context.get("funding_rate", "N/A")
        drift       = context.get("drift_status", "STABLE")
        kelly       = context.get("kelly_fraction", "N/A")
        atr_pct     = context.get("atr_pct", "N/A")
        daily_pnl   = context.get("daily_pnl", 0)
        open_pos    = context.get("open_positions", 0)

        prompt = f"""You are a risk management agent for a crypto trading system.
Evaluate whether it is SAFE to trade right now, considering:

Asset: {symbol} | Crisis Level: {crisis}/4 | Drift: {drift}
VIX: {vix} | Funding: {funding} | ATR%: {atr_pct}
Kelly Fraction: {kelly} | Daily P&L so far: {daily_pnl} | Open Positions: {open_pos}

Rules: if crisis>=3, drift==SHOCK, or daily_pnl < -2% → must return flat.
Otherwise evaluate risk holistically.

Respond ONLY with valid JSON (no markdown):
{{
  "signal": "long" or "short" or "flat",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<1-2 sentences on risk assessment>"
}}
Note: you may recommend "long" or "short" if risk is LOW and conditions are favorable,
but lean heavily toward "flat" when any risk indicator is elevated."""

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
            sig = str(parsed.get("signal", "flat"))
            return {
                "agent":      "risk_agent",
                "signal":     sig,
                "direction":  sig,
                "confidence": float(parsed.get("confidence", 0.6)),
                "reasoning":  str(parsed.get("reasoning", "")),
            }
        except Exception as e:
            log.warning(f"RiskAgent LLM parse error: {e}")
            # On error, default to caution
            return {"agent": "risk_agent", "signal": "flat", "direction": "flat",
                    "confidence": 0.7, "reasoning": "Risk assessment unavailable — defaulting to flat"}
