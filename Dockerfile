FROM python:3.12-slim-bookworm

# Copy the app and config files
COPY app /app
COPY conf /conf
COPY requirements.txt /requirements.txt

# Copy .env if it exists
COPY .env* /.env

# Set Hugging Face cache directory
RUN mkdir -p /app/.cache/huggingface
RUN chmod -R 777 /app/.cache
ENV HF_HOME=/app/.cache/huggingface

# Set Torch cache directory
ENV TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor_cache

# Add fake user entry so getpass.getuser() works
RUN echo "user:x:1000:1000:user:/home/user:/bin/bash" >> /etc/passwd

# Install dependencies
RUN pip install -r requirements.txt

CMD ["python", "-m", "app.app"]
