FROM python:3.12-slim
WORKDIR /app
COPY agent_system/requirements.txt agent_system/VERSION ./
RUN pip install --no-cache-dir -r requirements.txt
COPY agent_system/ ./
COPY shared/llm_providers.py ./llm_providers.py
COPY shared/groq_orchestrator.py ./groq_orchestrator.py
EXPOSE 8007
CMD ["python", "main.py"]
