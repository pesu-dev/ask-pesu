FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y git build-essential

WORKDIR /app

ENV HF_HOME=/root/.cache/huggingface
ENV TRANSFORMERS_CACHE=/root/.cache/huggingface

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python - <<'PY'
from sentence_transformers import SentenceTransformer
print("Pre-downloading model: Alibaba-NLP/gte-modernbert-base ...")
SentenceTransformer("Alibaba-NLP/gte-modernbert-base")
print("Done model cache.")
PY

COPY main.py .

EXPOSE 7860

CMD ["python", "main.py"]
