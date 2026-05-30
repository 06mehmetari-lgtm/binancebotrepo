# Role: Moderates Bull vs Bear debate and synthesizes final verdict.
import os, anthropic

MODEL = "claude-sonnet-4-6"

class DebateAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    def debate(self, bull_analysis: dict, bear_analysis: dict, context: dict) -> dict:
        prompt = (
            f"You are the debate moderator for a crypto trading system.\n\n"
            f"BULL CASE:\n{bull_analysis}\n\n"
            f"BEAR CASE:\n{bear_analysis}\n\n"
            f"MARKET CONTEXT:\n{context}\n\n"
            f"Synthesize both arguments and provide a final verdict as JSON: "
            f"{{direction, confidence, consensus_reasoning, dissent_risk}}"
        )
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )
        return {"agent": "debate_agent", "verdict": response.content[0].text}
