"""
Debate Agent — orchestrates 9 agents and synthesizes a final verdict.
Primary voting is rule-based (fast, no API cost per tick).
LLM synthesis: multi-key Groq rotation → LLM_PROVIDER_ORDER chain → Ollama.
"""

import asyncio
import json
import logging
import os
import urllib.request
from dataclasses import dataclass

from llm_providers import chat_completion, cloud_llm_disabled

logger = logging.getLogger(__name__)
GROQ_MODEL = os.getenv("GROQ_DEBATE_MODEL") or os.getenv("GROQ_LEARN_MODEL", "llama-3.3-70b-versatile")


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
    """
    Aggregates votes from all agents using weighted voting.
    Agent weights are updated based on historical accuracy.
    """

    DEFAULT_WEIGHTS = {
        "technical": 1.0, "onchain": 1.2, "sentiment": 0.8,
        "macro": 0.9, "news": 0.8, "bull": 1.0, "bear": 1.0,
        "neutral": 0.7, "risk": 1.1,
    }

    def __init__(self):
        self.weights = dict(self.DEFAULT_WEIGHTS)

    def _ollama_url(self) -> str | None:
        return os.getenv("OLLAMA_URL", "http://ollama:11434") or None

    async def run_debate(
        self, symbol: str, features: dict, context: dict, lessons: list[str] | None = None
    ) -> DebateResult:
        votes = await asyncio.gather(
            self._technical_vote(features),
            self._onchain_vote(context),
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

        if lessons and result.final_signal != "flat":
            lesson_hint = " | ".join(lessons[:2])
            result = DebateResult(
                final_signal=result.final_signal,
                final_confidence=result.final_confidence,
                consensus_strength=result.consensus_strength,
                all_votes=result.all_votes,
                majority_reasoning=f"{result.majority_reasoning} | Lessons: {lesson_hint}",
            )

        # LLM synthesis — only for high-confidence non-flat signals
        if result.final_signal != "flat" and result.final_confidence > 0.65:
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, self._llm_synthesize, symbol, features, context, result
                )
            except Exception as e:
                logger.debug(f"LLM synthesis skipped for {symbol}: {e}")

        return result

    def _llm_synthesize(self, symbol: str, features: dict,
                        context: dict, base: DebateResult) -> DebateResult:
        prompt = self._synthesis_prompt(symbol, features, context, base)
        local_only = cloud_llm_disabled()
        raw, provider = chat_completion(
            prompt,
            max_tokens=120,
            temperature=0.1,
            model_pool=None if local_only else "final",
            use_swarm=not local_only,
        )
        if not raw:
            ollama = self._ollama_url()
            if ollama:
                return self._ollama_synthesize(ollama, symbol, features, context, base)
            return base
        return self._parse_synthesis_response(raw, base, provider or "llm")

    def _synthesis_prompt(self, symbol: str, features: dict, context: dict, base: DebateResult) -> str:
        rsi = round(float(features.get("rsi_14", 50)), 1)
        macd = round(float(features.get("macd_hist", 0)), 4)
        regime = context.get("regime", "unknown")
        crisis = context.get("crisis_level", 0)
        fg = context.get("fear_greed", 50)
        return (
            f"Crypto trading signal for {symbol}. Rule-based agents voted: {base.final_signal.upper()} "
            f"with {base.final_confidence:.0%} confidence ({base.consensus_strength:.0%} consensus).\n"
            f"Key data: RSI={rsi}, MACD_hist={macd}, regime={regime}, "
            f"crisis_level={crisis}, fear_greed={fg}, "
            f"agent_reasoning='{base.majority_reasoning}'\n"
            f"Respond with JSON only: "
            f'{{\"signal\":\"long|short|flat\",\"confidence\":0.0-1.0,\"reasoning\":\"one sentence\"}}'
        )

    def _parse_synthesis_response(self, raw: str, base: DebateResult, provider: str) -> DebateResult:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json").strip()
        data = json.loads(text)
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
            majority_reasoning=f"[{provider}] {reasoning}",
        )

    def _ollama_synthesize(self, ollama_url: str, symbol: str, features: dict,
                           context: dict, base: DebateResult) -> DebateResult:
        model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        prompt = self._synthesis_prompt(symbol, features, context, base)

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
        try:
            timeout = float(os.getenv("OLLAMA_TIMEOUT", "240"))
        except ValueError:
            timeout = 240.0
        with urllib.request.urlopen(req, timeout=max(60.0, timeout)) as resp:
            result = json.loads(resp.read())

        raw = result["message"]["content"].strip()
        return self._parse_synthesis_response(raw, base, f"ollama/{model}")

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
        if confidence < 0.55:
            final = "flat"
        signals = [v.signal for v in votes]
        consensus = max(signals.count("long"), signals.count("short"), signals.count("flat")) / len(signals)
        supporting = [v.agent_name for v in votes if v.signal == final]
        opposing = [v.agent_name for v in votes if v.signal != final]
        return DebateResult(
            final_signal=final, final_confidence=confidence,
            consensus_strength=consensus, all_votes=votes,
            majority_reasoning=f"For: {supporting} | Against: {opposing}",
        )

    async def _technical_vote(self, f: dict) -> AgentVote:
        rsi = float(f.get("rsi_14", 50)) / 100
        macd = float(f.get("macd_hist", 0))
        adx = float(f.get("adx_14", 0))
        imb1 = float(f.get("imbalance_1", f.get("imbalance_5", 0)))
        imb5 = float(f.get("imbalance_5", 0))
        imb20 = float(f.get("imbalance_20", 0))
        bid_lv = int(f.get("bid_levels_active", 0))
        ask_lv = int(f.get("ask_levels_active", 0))
        score = (0.5 - rsi) * 2 + macd * 10
        score += imb1 * 0.35 + imb5 * 0.25 + imb20 * 0.15
        if adx > 0.25:
            score *= 1.2
        signal = "long" if score > 0.2 else ("short" if score < -0.2 else "flat")
        return AgentVote(
            "technical", signal, min(abs(score), 1.0),
            {
                "rsi": rsi, "macd": macd,
                "imb_l1": imb1, "imb_l5": imb5, "imb_l20": imb20,
                "bid_levels": bid_lv, "ask_levels": ask_lv,
            },
        )

    async def _onchain_vote(self, ctx: dict) -> AgentVote:
        funding = float(ctx.get("funding_rate", 0))
        ls = float(ctx.get("ls_ratio", 0))
        liq = float(ctx.get("liq_pressure", 0))
        netflow = float(ctx.get("onchain_netflow", 0))
        score = -funding * 100 - ls * 0.5 + netflow * 0.5 - liq * 0.3
        signal = "long" if score > 0.15 else ("short" if score < -0.15 else "flat")
        return AgentVote("onchain", signal, min(abs(score), 1.0), {"funding": funding, "netflow": netflow})

    async def _sentiment_vote(self, ctx: dict) -> AgentVote:
        reddit = float(ctx.get("reddit_sentiment", 0))
        fg = float(ctx.get("fear_greed", 50)) / 100
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
        if float(f.get("rsi_14", 50)) < 35: bull += 1
        if float(f.get("imbalance_5", 0)) > 0.2: bull += 1
        if float(ctx.get("fear_greed", 50)) < 25: bull += 1
        if float(ctx.get("onchain_netflow", 0)) > 0.2: bull += 1
        if float(ctx.get("ls_ratio", 0)) < -0.3: bull += 1
        conf = bull / 5
        return AgentVote("bull", "long" if conf > 0.4 else "flat", conf, {"bull_count": bull})

    async def _bear_vote(self, f: dict, ctx: dict) -> AgentVote:
        bear = 0
        if float(f.get("rsi_14", 50)) > 70: bear += 1
        if float(f.get("imbalance_5", 0)) < -0.2: bear += 1
        if float(ctx.get("fear_greed", 50)) > 80: bear += 1
        if float(ctx.get("funding_rate", 0)) > 0.002: bear += 1
        if float(ctx.get("vix_level", 20)) > 35: bear += 1
        conf = bear / 5
        return AgentVote("bear", "short" if conf > 0.4 else "flat", conf, {"bear_count": bear})

    async def _neutral_vote(self, f: dict) -> AgentVote:
        adx = float(f.get("adx_14", 0))
        if adx < 0.15:
            return AgentVote("neutral", "flat", 0.7, {"reason": "no trend"})
        return AgentVote("neutral", "flat", 0.3, {"reason": "trend present"})

    async def _risk_vote(self, f: dict, ctx: dict) -> AgentVote:
        crisis = int(ctx.get("crisis_level", 0))
        drift = ctx.get("drift_status", "STABLE")
        if crisis >= 3 or drift == "SHOCK":
            return AgentVote("risk", "flat", 0.9, {"crisis": crisis, "drift": drift})
        if crisis >= 2:
            return AgentVote("risk", "flat", 0.6, {"crisis": crisis})
        return AgentVote("risk", "flat", 0.2, {"crisis": crisis})

    def update_weights(self, agent_name: str, was_correct: bool):
        current = self.weights.get(agent_name, 1.0)
        if was_correct:
            self.weights[agent_name] = min(current * 1.05, 2.0)
        else:
            self.weights[agent_name] = max(current * 0.97, 0.3)
