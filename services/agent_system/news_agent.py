# Role: Processes news sentiment and CryptoPanic headlines.
import os, anthropic

MODEL = "claude-sonnet-4-6"

class NewsAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY', ''))
        self.role = 'Processes news sentiment and CryptoPanic headlines.'

    def analyze(self, context: dict) -> dict:
        prompt = f'You are a crypto trading agent. Role: {self.role}\n\nContext:\n{context}\n\nProvide your analysis as JSON with keys: signal, confidence, reasoning.'
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return {'agent': 'news_agent', 'response': response.content[0].text}
