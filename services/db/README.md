---
title: Ask PESU DB updater
short_description: A script that updates askPESU's DB automatically
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
- Qdrant/bm25
preload_from_hub:
- Alibaba-NLP/gte-modernbert-base
tags:
- assistant
- question answering
- pes university
- reddit
- bot
---

# askPESU DB updater

Keeps askPESU's search index current. It watches r/PESU for new comments and,
for each one, re-indexes the whole thread that comment belongs to.

Threads rather than comments are the unit of indexing: a reply like "yes, around
8.5" means nothing on its own, so each document carries the post title, the post
body and the full comment tree. The point id is derived from the thread's root
comment, so a busy thread is repeatedly overwritten instead of accumulating
near-duplicates.

Every point is written with two vectors - a dense embedding and a BM25 sparse
vector - so the reader can move to hybrid retrieval without re-embedding the
collection.

The collection is created from `conf/collection.yaml` if it does not exist, and
validated against it if it does. Every payload is checked before it is written.
A payload that disagrees stops the listener and turns `/health` into a 503,
because a writer that keeps going is worse than one that visibly stops: the
reader, [askpesu](https://huggingface.co/spaces/pesu-dev/askpesu), depends on
what lands here.

This Space only sees comments posted after it starts. History is loaded
separately with `scripts/populate_db.py`.

There is no interface to speak of: `/` is a status page and `/health` reports
whether the listener is still running.

**Configuration.** `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `QDRANT_URL`,
`QDRANT_API_KEY` and `QDRANT_COLLECTION` are set as Space secrets. Startup fails
immediately if the Reddit credentials are missing or rejected.

**Source.** This Space is deployed from the
[ask-pesu monorepo](https://github.com/pesu-dev/ask-pesu) - it is the
`services/db` directory published as its own repository root, so pull requests
belong there, not here.
