"""
Debate Agent — orchestrates 9 agents and synthesizes a final verdict.
Primary voting is rule-based (fast, no API cost per tick).
LLM synthesis: Groq → Cerebras → SambaNova → OpenRouter → Ollama (auto-fallback).
"""

import asyncio
import json
import logging
import os
import urllib.request
import urllib.error
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AgentVote:
    agent_name: str
    signal: str        # "long", "short", "flat"
    confidence: float  # 0-1
    reasoning: dict


@dataclass
class DebateResult:
    final_signal: str
    final_confidence: float
    consensus_strength: float
    all_votes: list
    majority_reasoning: str


class DebateAgent:
    DEFAULT_WEIGHTS = {
        "technical": 1.0, "onchain": 1.2, "sentiment": 0.8,
        "macro": 0.9, "news": 0.8, "bull": 1.0, "bear": 1.0,
        "neutral": 0.7, "risk": 1.1,
    }

    def __init__(self):
        self.weights = dict(self.DEFAULT_WEIGHTS)

    def _ollama_url(self) -> str | None:
        return os.getenv("OLLAMA_URL", "http://ollama:11434") or None

    # ── Main debate orchestration ─────────────────────────────────────────────

    async def run_debate(
        self, symbol: str, features: dict, context: dict,
        training_context: str = "",
        rag_block: str = "",
    ) -> DebateResult:
        votes = await asyncio.gather(
            self._technical_vote(features),
            self._onchain_vote(features, context),
            self._sentiment_vote(context),
            self._macro_vote(context),
            self._bull_vote(features, context),
            self._bear_vote(features, context),
            self._neutral_vote(features),
            self._risk_vote(features, context),
            return_exceptions=True,
        )
        valid = [v for v in votes if isinstance(v, AgentVote)]
        if not valid:
            return DebateResult("flat", 0, 0, [], "no votes")

        result = self._aggregate(valid)

        # LLM synthesis — only for high-confidence non-flat signals
        if result.final_signal != "flat" and result.final_confidence > 0.65:
            # Geçmiş benzer durumları training_context'e ekle (Faz 3 RAG)
            enriched_context = training_context
            if rag_block:
                enriched_context = (
                    training_context + "\n\n===\n\n" + rag_block
                    if training_context else rag_block
                )
            result = await self._synthesize(symbol, features, context, result, enriched_context)

        return result

    async def _synthesize(self, symbol: str, features: dict,
                          context: dict, base: DebateResult,
                          training_context: str = "") -> DebateResult:
        prompt = self._build_prompt(symbol, features, context, base, training_context)

        # 1. Multi-provider fallback chain (Groq → Cerebras → SambaNova → OpenRouter)
        try:
            from llm_client import chat_completion
            raw, provider = await chat_completion(prompt, max_tokens=120)
            return self._parse_llm_response(raw, base, provider)
        except Exception as e:
            logger.debug(f"LLM synthesis failed for {symbol}: {e} — Ollama deneniyor")

        # 2. Ollama local fallback (always available when container is up)
        ollama = self._ollama_url()
        if ollama:
            loop = asyncio.get_event_loop()
            try:
                return await loop.run_in_executor(
                    None, self._ollama_synthesize, ollama, symbol, features, context, base, training_context
                )
            except Exception as e:
                logger.debug(f"Ollama synthesis skipped for {symbol}: {e}")

        return base

    def _build_prompt(self, symbol: str, features: dict,
                      context: dict, base: DebateResult,
                      training_context: str = "") -> str:
        rsi    = round(float(features.get("rsi_14", 50)), 1)
        macd   = round(float(features.get("macd_hist", 0)), 4)
        bb_pos = round(float(features.get("bb_position", 0.5)), 2)
        atr_p  = round(float(features.get("atr_pct", 0)) * 100, 2)
        vol_r  = round(float(features.get("volume_ratio", 1)), 2)
        regime = context.get("regime", "unknown")
        crisis = context.get("crisis_level", 0)
        fg     = context.get("fear_greed", 50)
        fund   = round(float(context.get("funding_rate", 0)) * 100, 4)
        drift  = context.get("drift_status", "STABLE")
        operator_block = (
            f"OPERATOR INSTRUCTIONS (must be followed above all else):\n{training_context.strip()}\n\n"
            if training_context.strip() else ""
        )
        return (
            f"{operator_block}"
            f"Crypto futures trading signal synthesis for {symbol}.\n"
            f"Rule-based agent consensus: {base.final_signal.upper()} "
            f"confidence={base.final_confidence:.0%} consensus={base.consensus_strength:.0%}\n"
            f"Technical: RSI={rsi}, MACD_hist={macd}, BB_pos={bb_pos}, "
            f"ATR%={atr_p}%, vol_ratio={vol_r}x\n"
            f"Market: regime={regime}, crisis_level={crisis}, fear_greed={fg}, "
            f"funding={fund}%, drift={drift}\n"
            f"Agent reasoning: {base.majority_reasoning}\n\n"
            f'Respond with JSON only (no markdown): '
            f'{{"signal":"long|short|flat","confidence":0.0-1.0,"reasoning":"max 15 words"}}'
        )

    def _parse_llm_response(self, raw: str, base: DebateResult, tag: str) -> DebateResult:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        data = json.loads(raw)
        signal = data.get("signal", base.final_signal)
        confidence = float(data.get("confidence", base.final_confidence))
        reasoning = data.get("reasoning", base.majority_reasoning)
        if signal not in ("long", "short", "flat"):
            signal = base.final_signal
        return DebateResult(
            final_signal=signal,
            final_confidence=confidence,
            consensus_strength=base.consensus_strength,
            all_votes=base.all_votes,
            majority_reasoning=f"[{tag}] {reasoning}",
        )

    def _ollama_synthesize(self, ollama_url: str, symbol: str, features: dict,
                           context: dict, base: DebateResult,
                           training_context: str = "") -> DebateResult:
        model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        prompt = self._build_prompt(symbol, features, context, base, training_context)
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 120},
        }).encode()
        req = urllib.request.Request(
            f"{ollama_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        raw = result["message"]["content"]
        return self._parse_llm_response(raw, base, f"Ollama/{model}")

    # ── Vote aggregation ──────────────────────────────────────────────────────

    def _aggregate(self, votes: list[AgentVote]) -> DebateResult:
        scores = {"long": 0.0, "short": 0.0, "flat": 0.0}
        total_w = 0.0
        for v in votes:
            w = self.weights.get(v.agent_name, 1.0)
            scores[v.signal] = scores.get(v.signal, 0) + v.confidence * w
            total_w += w
        if total_w > 0:
            scores = {k: v / total_w for k, v in scores.items()}
        final = max(scores, key=scores.__getitem__)
        confidence = scores[final]
        if confidence < 0.50:
            final = "flat"
        signals = [v.signal for v in votes]
        consensus = max(signals.count("long"), signals.count("short"), signals.count("flat")) / len(signals)
        supporting = [v.agent_name for v in votes if v.signal == final]
        opposing   = [v.agent_name for v in votes if v.signal != final]
        return DebateResult(
            final_signal=final, final_confidence=confidence,
            consensus_strength=consensus, all_votes=votes,
            majority_reasoning=f"For: {supporting} | Against: {opposing}",
        )

    # ── Individual agent votes (rule-based, fast) ─────────────────────────────

    async def _technical_vote(self, f: dict) -> AgentVote:
        rsi          = float(f.get("rsi_14", 50)) / 100
        macd         = float(f.get("macd_hist", 0))
        adx          = float(f.get("adx_14", 0))
        imb          = float(f.get("imbalance_5", 0))
        trend_align  = float(f.get("trend_alignment", 0))   # MTF: -1 to +1
        rsi_1h       = float(f.get("rsi_14_1h", 50)) / 100  # 1h RSI normalized
        va_pos       = float(f.get("va_position", 0))        # -1 discount / 0 inside / +1 premium
        score = (0.5 - rsi) * 2 + macd * 10 + imb * 0.5
        score += trend_align * 0.3          # MTF confirmation
        score += (0.5 - rsi_1h) * 0.4      # 1h RSI extra weight
        score -= va_pos * 0.2               # at premium → slightly bearish bias
        if adx > 0.25:
            score *= 1.2
        signal = "long" if score > 0.2 else ("short" if score < -0.2 else "flat")
        return AgentVote("technical", signal, min(abs(score), 1.0), {"rsi": rsi, "macd": macd, "trend_align": trend_align})

    async def _onchain_vote(self, f: dict, ctx: dict) -> AgentVote:
        funding   = float(ctx.get("funding_rate", 0))
        ls        = float(ctx.get("ls_ratio", 0))
        liq       = float(ctx.get("liq_pressure", 0))
        netflow   = float(ctx.get("onchain_netflow", 0))
        cvd_5m    = float(f.get("cvd_5m", 0))         # +1 = pure buy, -1 = pure sell
        liq_ratio = float(f.get("liq_ratio_1h", 0))   # positive = more short liquidations (bullish)
        score = -funding * 100 - ls * 0.5 + netflow * 0.5 - liq * 0.3
        score += cvd_5m * 0.4       # real-time buy/sell pressure
        score += liq_ratio * 0.25   # liquidation cascade direction
        signal = "long" if score > 0.15 else ("short" if score < -0.15 else "flat")
        return AgentVote("onchain", signal, min(abs(score), 1.0), {"funding": funding, "cvd_5m": cvd_5m})

    async def _sentiment_vote(self, ctx: dict) -> AgentVote:
        reddit = float(ctx.get("reddit_sentiment", 0))
        fg     = float(ctx.get("fear_greed", 50)) / 100
        contrarian_fg = 1 - fg
        score = reddit * 0.4 + contrarian_fg * 0.6
        signal = "long" if score > 0.6 else ("short" if score < 0.4 else "flat")
        conf = abs(score - 0.5) * 2
        return AgentVote("sentiment", signal, min(conf, 1.0), {"reddit": reddit, "fear_greed": fg})

    async def _macro_vote(self, ctx: dict) -> AgentVote:
        vix = float(ctx.get("vix_level", 20))
        dxy = float(ctx.get("dxy_change_1d", 0))
        score = -(vix - 20) / 40 - dxy * 2
        signal = "long" if score > 0.1 else ("short" if score < -0.1 else "flat")
        return AgentVote("macro", signal, min(abs(score), 1.0), {"vix": vix, "dxy": dxy})

    async def _bull_vote(self, f: dict, ctx: dict) -> AgentVote:
        bull = 0
        if float(f.get("rsi_14", 50)) < 35:              bull += 1
        if float(f.get("imbalance_5", 0)) > 0.2:         bull += 1
        if float(ctx.get("fear_greed", 50)) < 25:         bull += 1
        if float(ctx.get("onchain_netflow", 0)) > 0.2:    bull += 1
        if float(ctx.get("ls_ratio", 0)) < -0.3:          bull += 1
        if float(f.get("cvd_5m", 0)) > 0.2:               bull += 1  # strong buy pressure
        if float(f.get("bull_confluence", 0)) >= 2:        bull += 1  # both TFs agree bullish
        if float(f.get("os_1h", 0)) == 1.0:               bull += 1  # 1h oversold reversal setup
        conf = bull / 8
        return AgentVote("bull", "long" if conf > 0.35 else "flat", conf, {"bull_count": bull})

    async def _bear_vote(self, f: dict, ctx: dict) -> AgentVote:
        bear = 0
        if float(f.get("rsi_14", 50)) > 65:              bear += 1  # was 70
        if float(f.get("imbalance_5", 0)) < -0.15:       bear += 1  # was -0.2
        if float(ctx.get("fear_greed", 50)) > 75:         bear += 1  # was 80
        if float(ctx.get("funding_rate", 0)) > 0.001:     bear += 1  # was 0.002
        if float(ctx.get("vix_level", 20)) > 35:          bear += 1
        if float(f.get("cvd_5m", 0)) < -0.2:              bear += 1  # strong sell pressure
        if float(f.get("bear_confluence", 0)) >= 2:        bear += 1  # both TFs agree bearish
        if float(f.get("ob_1h", 0)) == 1.0:               bear += 1  # 1h overbought reversal setup
        conf = bear / 8
        return AgentVote("bear", "short" if conf > 0.35 else "flat", conf, {"bear_count": bear})

    async def _neutral_vote(self, f: dict) -> AgentVote:
        adx = float(f.get("adx_14", 0))
        rsi = float(f.get("rsi_14", 50))
        macd = float(f.get("macd_hist", 0))
        if adx < 0.15:
            return AgentVote("neutral", "flat", 0.6, {"reason": "no trend"})
        # Trend present — vote with momentum direction
        score = (rsi - 50) / 50 + macd * 5
        if score > 0.15:
            return AgentVote("neutral", "long", min(0.5, abs(score)), {"reason": "momentum up"})
        elif score < -0.15:
            return AgentVote("neutral", "short", min(0.5, abs(score)), {"reason": "momentum down"})
        return AgentVote("neutral", "flat", 0.3, {"reason": "mixed momentum"})

    async def _risk_vote(self, f: dict, ctx: dict) -> AgentVote:
        crisis = int(ctx.get("crisis_level", 0))
        drift  = ctx.get("drift_status", "STABLE")
        if crisis >= 3 or drift == "SHOCK":
            return AgentVote("risk", "flat", 0.9, {"crisis": crisis, "drift": drift})
        if crisis >= 2:
            return AgentVote("risk", "flat", 0.6, {"crisis": crisis})
        # Safe conditions — minimal influence, don't block other agents
        return AgentVote("risk", "flat", 0.1, {"crisis": crisis})

    def update_weights(self, agent_name: str, was_correct: bool):
        current = self.weights.get(agent_name, 1.0)
        if was_correct:
            self.weights[agent_name] = min(current * 1.05, 2.0)
        else:
            self.weights[agent_name] = max(current * 0.97, 0.3)
