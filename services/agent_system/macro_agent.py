# Role: Analyzes macroeconomic context (Fed, DXY, VIX, yield curve).
import os, anthropic

MODEL = "claude-sonnet-4-6"

class MacroAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY', ''))
        self.role = 'Analyzes macroeconomic context (Fed, DXY, VIX, yield curve).'

    def analyze(self, context: dict) -> dict:
        prompt = f'You are a crypto trading agent. Role: {self.role}\n\nContext:\n{context}\n\nProvide your analysis as JSON with keys: signal, confidence, reasoning.'
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return {'agent': 'macro_agent', 'response': response.content[0].text}
