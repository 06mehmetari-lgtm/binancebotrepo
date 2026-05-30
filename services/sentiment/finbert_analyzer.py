from transformers import pipeline

_pipe = None

def get_pipeline():
    global _pipe
    if _pipe is None:
        _pipe = pipeline("text-classification", model="ProsusAI/finbert")
    return _pipe

def analyze(text: str) -> dict:
    result = get_pipeline()(text[:512])[0]
    return {"label": result["label"], "score": result["score"]}
