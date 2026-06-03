FROM python:3.12-slim
WORKDIR /app
COPY learning_engine/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY learning_engine/ ./
COPY shared/llm_providers.py ./llm_providers.py
CMD ["python", "main.py"]
