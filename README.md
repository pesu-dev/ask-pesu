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

## The collection contract

`services/db` **writes** the Qdrant collection; `services/api` **reads** it. They must agree on
the collection name, embedding model, vector dimensions, distance metric, vector naming, and
payload schema. A mismatch corrupts retrieval quietly, so the agreement is written down once in
[`conf/collection.yaml`](conf/collection.yaml) and enforced by [`conf/contract.py`](conf/contract.py):

- **The writer** creates the collection from the contract, refuses to write into one whose
  geometry disagrees, and rejects any payload whose key set differs from the contracted list.
- **The reader** refuses to start unless the live collection matches the contract, the loaded
  embedding model is the contracted one at the contracted dimension, and every payload key it
  consumes is one the contract guarantees is written.
- **CI** checks the contract in [`tests/`](tests/test_contract.py).

Change it in `conf/`, never in a service.

## Layout

```
.
├── conf/
│   ├── collection.yaml      # the shared Qdrant contract (authored here)
│   └── contract.py          # loader + startup enforcement (authored here)
├── scripts/sync_contract.py # vendors both into each service; --check gates CI
├── pyproject.toml           # shared ruff + pytest configuration (no runtime deps)
├── tests/                   # contract tests
├── .pre-commit-config.yaml
└── services/
    ├── api/                 # own README, Dockerfile, deps + vendored contract
    └── db/                  # own README, Dockerfile, deps + vendored contract
```

Each service directory is self-contained and shaped like a repository root — its own
`README.md` (carrying that Space's frontmatter), `Dockerfile`, and dependencies. Deploy
workflows use `git subtree split` to push a single service directory to its Space, so the
Space receives a tree identical to what that service would look like standing alone.

That is also why the contract is **vendored**: a subtree split ships only `services/<name>/`,
so a repo-root file would simply not exist at runtime. `services/*/conf/collection.yaml` and
`services/*/app/contract.py` are generated copies — edit the originals under `conf/` and run:

```bash
python3 scripts/sync_contract.py
```

The pre-commit hook does this automatically, and CI fails on drift or on a subtree that would
deploy without the contract.

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
