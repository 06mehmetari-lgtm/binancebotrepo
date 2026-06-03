FROM python:3.12-slim
WORKDIR /app
COPY learning_engine/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY learning_engine/ ./
COPY shared/llm_providers.py ./llm_providers.py
COPY shared/groq_orchestrator.py ./groq_orchestrator.py
COPY shared/llm_status.py ./llm_status.py
COPY shared/proxy_pool.py ./proxy_pool.py
CMD ["python", "main.py"]
