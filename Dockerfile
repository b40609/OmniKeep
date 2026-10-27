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
    PORT=5000 \
    DATABASE_PATH=/data/omnikeep.db \
    SNAPSHOT_DIR=/data/snapshots \
    BACKUP_DIR=/data/backups

WORKDIR /app

# Install minimal OS dependencies for network, audio extraction & compiling C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy static assets (manifest.json, icons, etc.)
COPY static ./static

# Copy compiled frontend assets from Stage 1 into static/dist
COPY --from=frontend-builder /build/static/dist ./static/dist

# Copy backend source code
COPY app ./app
COPY run.py ./

# Persistent storage mount point for database, HTML snapshots, and rotating backups
RUN mkdir -p /data/snapshots /data/backups

VOLUME ["/data"]

EXPOSE 5000

# Healthcheck against public unauthenticated /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

CMD ["python", "run.py"]
