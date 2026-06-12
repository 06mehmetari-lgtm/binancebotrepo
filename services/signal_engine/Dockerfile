FROM python:3.12-slim
WORKDIR /app
COPY signal_engine/requirements.txt signal_engine/VERSION ./
RUN pip install --no-cache-dir psycopg2-binary==2.9.9 \
    && pip install --no-cache-dir -r requirements.txt
COPY signal_engine/ ./
COPY shared/risk_limits.py ./risk_limits.py
COPY shared/profit_rules.py ./profit_rules.py
COPY shared/outcome_predictor.py ./outcome_predictor.py
COPY shared/risk_model.py ./risk_model.py
COPY shared/signal_detector.py ./signal_detector.py
COPY shared/decision_payload.py ./decision_payload.py
EXPOSE 8008
CMD ["python", "main.py"]
