---
title: Ask PESU [DEV]
short_description: "A RAG pipeline for question answering about PES University"
emoji: 🦀
colorFrom: blue
colorTo: orange
sdk: docker
python_version: 3.12
app_file: app/app.py
app_port: 7860
fullWidth: true
header: mini
pinned: false
license: mit
disable_embedding: false

thumbnail: https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcT0VZcBflk0Q1auwPmjuXgoBj-VzFd9Iz_JfA&s
models:
    - Alibaba-NLP/gte-modernbert-base
preload_from_hub:
    - Alibaba-NLP/gte-modernbert-base
tags:
    - rag
    - assistant
    - question answering
    - pes university
---
