FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir asyncpg>=0.29 numpy>=1.26 pandas>=2.2
COPY run.py .
CMD ["python", "-u", "run.py"]
