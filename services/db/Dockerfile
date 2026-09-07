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

# Hugging Face Spaces run the container as uid 1000, and several libraries
# call getpass.getuser(), which fails without a matching passwd entry.
RUN echo "user:x:1000:1000:user:/home/user:/bin/bash" >> /etc/passwd \
    && mkdir -p /home/user && chown -R 1000:1000 /home/user

# Install dependencies
# torch is pinned to the +cpu build, which is published only on PyTorch's own
# index -- both Spaces run on CPU, and the CUDA wheels were ~4 GB of the image
# for libraries that are never loaded. requirements.txt pins the exact +cpu
# version, and PyPI has no such wheel, so this resolves deterministically.
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
COPY . /app
# Drop privileges. Everything above needed root to install packages; the
# service itself only reads /app and writes the caches, which are already
# world-writable.
USER 1000

# Set Python path to include the app directory
ENV PYTHONPATH=/app

CMD ["python", "-m", "app.app"]
