# Python backend stage
FROM python:3.12-slim-bookworm

# Set working directory
WORKDIR /app

COPY requirements.txt /app/

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
COPY . /app
# Set Python path to include the app directory
ENV PYTHONPATH=/app

CMD ["python", "-m", "app.app"]