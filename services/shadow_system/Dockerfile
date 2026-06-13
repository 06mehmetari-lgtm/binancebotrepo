FROM python:3.12-slim
WORKDIR /app
COPY shadow_system/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shadow_system/ ./
COPY shared/risk_limits.py ./risk_limits.py
COPY shared/profit_rules.py ./profit_rules.py
COPY shared/learn_entry.py ./learn_entry.py
COPY shared/portfolio_cap.py ./portfolio_cap.py
COPY shared/price_resolver.py ./price_resolver.py
COPY shared/portfolio_try.py ./portfolio_try.py
COPY oms/portfolio_sync.py ./portfolio_sync.py
EXPOSE 8011
CMD ["python", "main.py"]
