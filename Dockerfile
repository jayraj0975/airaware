# 1. Build the React frontend
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2. The API server, which also serves the built frontend
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY airaware airaware
COPY data/*.csv data/
COPY --from=frontend /frontend/dist frontend/dist
RUN useradd --create-home airaware && chown -R airaware /app
USER airaware
EXPOSE 8000
# data/ holds the database and refreshed data: mount it as a volume so they survive restarts.
CMD ["uvicorn", "airaware.server.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
