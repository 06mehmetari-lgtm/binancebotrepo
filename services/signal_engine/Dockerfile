FROM python:3.12-slim
WORKDIR /app
COPY signal_engine/requirements.txt signal_engine/VERSION ./
RUN pip install --no-cache-dir psycopg2-binary==2.9.9 \
    && pip install --no-cache-dir -r requirements.txt
COPY signal_engine/ ./
COPY shared/risk_limits.py ./risk_limits.py
EXPOSE 8008
CMD ["python", "main.py"]
