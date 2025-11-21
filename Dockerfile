# Multi-stage build for frontend and backend
FROM node:24-alpine AS frontend-builder

# Set working directory for frontend
WORKDIR /app/frontend

# Copy frontend package files
COPY frontend/package*.json ./

# Install frontend dependencies (including dev dependencies for build)
RUN npm ci

# Copy frontend source code
COPY frontend/ ./

# Build the frontend for production
RUN npm run build

# Python backend stage
FROM python:3.12-slim-bookworm

# Set working directory
WORKDIR /app

# Copy the app and config files
COPY app /app/app
COPY conf /app/conf
COPY requirements.txt /app/requirements.txt

# Copy .env if it exists
COPY .env* /app/

# Copy the built frontend files from the frontend stage
COPY --from=frontend-builder /app/frontend/out frontend/out

# Set Hugging Face cache directory
RUN mkdir -p /app/.cache/huggingface
RUN chmod -R 777 /app/.cache
ENV HF_HOME=/app/.cache/huggingface

# Set Torch cache directory
ENV TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor_cache

# Add fake user entry so getpass.getuser() works
RUN echo "user:x:1000:1000:user:/home/user:/bin/bash" >> /etc/passwd && mkdir -p /home/user

# Install dependencies
RUN pip install -r requirements.txt

# Set Python path to include the app directory
ENV PYTHONPATH=/app

CMD ["python", "-m", "app.app"]
