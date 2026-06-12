FROM python:3.12-slim
WORKDIR /app
COPY oms/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY oms/ ./
COPY shared/risk_limits.py ./risk_limits.py
COPY shared/portfolio_try.py ./portfolio_try.py
COPY shared/position_plan.py ./position_plan.py
EXPOSE 8010
CMD ["python", "main.py"]
