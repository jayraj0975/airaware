FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY airaware airaware
COPY web web
COPY data/*.csv data/
EXPOSE 8000
# Data refreshes itself in the background; mount data/ as a volume to keep refreshed data across restarts.
CMD ["uvicorn", "airaware.web:app", "--host", "0.0.0.0", "--port", "8000"]
