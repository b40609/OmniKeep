# Multi-stage Dockerfile for OmniKeep (Zero-config single container self-hosting)

# Stage 1: Build Vue 3 Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /build

# Install frontend dependencies
COPY frontend/package*.json ./frontend/
WORKDIR /build/frontend
RUN npm ci --prefer-offline || npm install

# Build frontend production bundle
COPY frontend/ ./
RUN npm run build

# Stage 2: Python 3.12 Runtime
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATABASE_PATH=/data/omnikeep.db \
    SNAPSHOT_DIR=/data/snapshots \
    BACKUP_DIR=/data/backups

WORKDIR /app

# Install minimal OS dependencies for network & compiling C extensions if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY app ./app
COPY run.py ./

# Copy compiled frontend assets from Stage 1 into static/dist
COPY --from=frontend-builder /build/static/dist ./static/dist

# Persistent storage mount point for database, HTML snapshots, and rotating backups
RUN mkdir -p /data/snapshots /data/backups

VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/items/stats || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
