FROM python:3.12-slim
WORKDIR /app
COPY shadow_system/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shadow_system/ ./
COPY shared/risk_limits.py ./risk_limits.py
EXPOSE 8011
CMD ["python", "main.py"]
