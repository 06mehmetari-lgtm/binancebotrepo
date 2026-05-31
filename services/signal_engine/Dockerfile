FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt VERSION ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8008
CMD ["python", "main.py"]
