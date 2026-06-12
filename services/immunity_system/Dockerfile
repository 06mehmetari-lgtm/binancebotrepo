FROM python:3.12-slim
WORKDIR /app
COPY immunity_system/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY immunity_system/ ./
COPY shared/risk_limits.py ./risk_limits.py
COPY shared/profit_rules.py ./profit_rules.py
EXPOSE 8009
CMD ["python", "main.py"]
