# ask-pesu

A retrieval-augmented question answering system for PES University, answering from
[r/PESU](https://www.reddit.com/r/PESU/) discussions.

This is a monorepo containing both halves of the system. They are deployed as separate
Hugging Face Spaces but share one Qdrant collection, and therefore one schema contract.

## Services

| Path | What it does | Space |
|---|---|---|
| [`services/api`](services/api) | FastAPI + LangChain RAG backend, and the React frontend it serves | [`askpesu`](https://huggingface.co/spaces/pesu-dev/askpesu) (prod), [`askpesu-dev`](https://huggingface.co/spaces/pesu-dev/askpesu-dev) (staging) |
| [`services/db`](services/db) | Reddit listener that streams new r/PESU comment threads into Qdrant | [`askpesu-db`](https://huggingface.co/spaces/pesu-dev/askpesu-db) |

`services/db` **writes** the Qdrant collection; `services/api` **reads** it. They must agree on
the collection name, embedding model, vector dimensions, distance metric, and vector naming.
That agreement is written down in [`conf/collection.yaml`](conf/collection.yaml) — change it
there, for both services, rather than in either service alone.

## Layout

```
.
├── conf/collection.yaml     # shared Qdrant schema contract
├── pyproject.toml           # shared ruff + pytest configuration (no runtime deps)
├── .pre-commit-config.yaml
└── services/
    ├── api/                 # own README, Dockerfile, deps
    └── db/                  # own README, Dockerfile, deps
```

Each service directory is self-contained and shaped like a repository root — its own
`README.md` (carrying that Space's frontmatter), `Dockerfile`, and dependencies. Deploy
workflows use `git subtree split` to push a single service directory to its Space, so the
Space receives a tree identical to what that service would look like standing alone.

## Development

Each service is developed from within its own directory; see
[`services/api/README.md`](services/api/README.md) and
[`services/db/README.md`](services/db/README.md).

Linting and formatting are configured once at the repository root and cover both services:

```bash
pip install pre-commit
pre-commit run --all-files
```

## Contributing

Pull requests **must** come from a fork and **must** target `dev`; CI enforces both.
`main` is a deploy artifact and is advanced only by the production deploy workflow.
See [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md).
