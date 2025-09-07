# =========================
# Stage 1: Build frontend
# =========================
FROM node:24.5.0-alpine AS frontend-builder

RUN mkdir /frontend

# Copy package files and install dependencies
COPY frontend/package*.json ./
# RUN npm install

# Copy the rest of the frontend source
COPY frontend/ ./

# Build the frontend (Next.js with output: "export")
# RUN npm run build && ls -l out

# Test
RUN mkdir /frontend/testdir && echo "hello from testdir" > /frontend/testdir/hello.txt

# =========================
# Stage 2: Python backend
# =========================
FROM python:3.12-slim-bookworm

# Copy backend code and requirements
COPY app /app
COPY conf /conf
COPY requirements.txt /requirements.txt

# Copy .env if exists
COPY .env* /.env

# Install Python dependencies
# RUN pip install --no-cache-dir -r requirements.txt

# Copy the frontend build output from the frontend-builder stage into /out
# COPY --from=frontend-builder /frontend/out/. /out/
COPY --from=frontend-builder /frontend/testdir /testdir

# Expose port
EXPOSE 7860

# Run FastAPI
CMD ["python", "-m", "app.app"]