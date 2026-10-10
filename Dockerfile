# 1. Build the React frontend
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2. The API server, which also serves the built frontend
FROM python:3.12-slim
# Forecast days are Indian calendar days: on UTC the site called today "yesterday" until 5:30 am IST.
ENV TZ=Asia/Kolkata
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY airaware airaware
# Starting data, copied into the data volume on first start (a fresh Railway or Docker volume is empty).
COPY data/*.csv seed/
COPY --from=frontend /frontend/dist frontend/dist
RUN mkdir data && useradd --create-home airaware && chown -R airaware /app
COPY docker-entrypoint.sh .
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
# data/ holds the database and refreshed data: mount it as a volume so they survive restarts.
# No access log: it would record every looked-up location next to the visitor's IP (see the Privacy Notice).
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "airaware.server.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--no-access-log"]
