# Stage 1: Build frontend
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python app with built frontend
FROM python:3.13-slim
WORKDIR /app

# System dependencies for OpenCV, Tesseract, and rawpy
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python package
COPY pyproject.toml README.md ./
COPY cataloguer/ cataloguer/
RUN pip install --no-cache-dir ".[web]"

# Copy built frontend into the static directory
COPY --from=frontend-build /app/cataloguer/api/static/dist/ cataloguer/api/static/dist/

# Default port
EXPOSE 8000

# Data volume for the database
VOLUME /data

ENV DATABASE_PATH=/data/collection.db

CMD ["uvicorn", "cataloguer.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
