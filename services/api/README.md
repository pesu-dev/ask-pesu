---
title: Ask PESU
short_description: A RAG pipeline for question answering about PES University
emoji: 🦀
colorFrom: yellow
colorTo: red
sdk: docker
python_version: 3.12
app_file: app/app.py
app_port: 7860
fullWidth: true
header: mini
pinned: false
license: mit
disable_embedding: false
thumbnail: >-
  https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcT0VZcBflk0Q1auwPmjuXgoBj-VzFd9Iz_JfA&s
models:
- Alibaba-NLP/gte-modernbert-base
- cross-encoder/ms-marco-MiniLM-L-6-v2
- Qwen/Qwen3-4B-Instruct-2507
- Qwen/Qwen3-4B-Thinking-2507
preload_from_hub:
- Alibaba-NLP/gte-modernbert-base
- cross-encoder/ms-marco-MiniLM-L-6-v2
tags:
- rag
- assistant
- question answering
- pes university
---

# askPESU

Retrieval-augmented question answering about PES University, answered from
r/PESU discussions. This Space serves both the API and the web UI from one
origin.

A question is rewritten into a standalone query, expanded into several
phrasings, matched against a Qdrant collection of Reddit comment threads,
reranked by a cross-encoder, and answered with the surviving threads as context
and a Sources list linking back to them. If nothing clears the relevance
threshold the model says so rather than inventing an answer.

The collection it reads is written by the companion Space,
[askpesu-db](https://huggingface.co/spaces/pesu-dev/askpesu-db). Both agree on
the collection's shape through `conf/collection.yaml`, which each verifies at
startup, so a mismatch stops the Space rather than producing quietly wrong
retrieval.

| Route | Purpose |
|---|---|
| `GET /` | the web UI |
| `POST /ask` | ask a question; answers stream back as newline-delimited JSON |
| `POST /rewriteQuery` | condense a question into a conversation title |
| `GET /health` | liveness |
| `GET /quota` | per-model cooldown state |
| `GET /docs` | OpenAPI documentation |

**Configuration.** `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION` and
`HF_TOKEN` are set as Space secrets. Everything else is in `conf/config.yaml`.

**Source.** This Space is deployed from the
[ask-pesu monorepo](https://github.com/pesu-dev/ask-pesu) - it is the
`services/api` directory published as its own repository root, so pull requests
belong there, not here.
