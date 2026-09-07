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
payload schema. A mismatch corrupts retrieval quietly, so all of it is written down **once**, in
[`conf/collection.yaml`](conf/collection.yaml), and both services load that file:

- **The writer** creates the collection from the contract, refuses to write into one whose
  geometry disagrees, and rejects any payload whose key set differs from the contracted list.
- **The reader** refuses to start unless the live collection matches the contract, the loaded
  embedding model is the contracted one at the contracted width, and every payload key it
  consumes is one the contract guarantees is written.
- **CI** checks all of it in [`tests/`](tests/test_contract.py), and asserts that
  `conf/collection.yaml` is the only contract file tracked in git.

Each service reads it through its own small `app/contract.py`. Change values in `conf/`, never
in a service.

### Why builds copy it

`conf/collection.yaml` lives at the repo root, but each service is deployed with
`git subtree split --prefix=services/<name>`, which ships **only that directory** — the repo root
never reaches the running Space. So image builds and deploys copy the file into
`services/<name>/conf/` first, and the deploy workflows refuse to push a tree that lacks it.

That copy is generated, never committed (`.gitignore` covers it). To build or run a service
locally, do the same thing first:

```bash
mkdir -p services/api/conf && cp conf/collection.yaml services/api/conf/
docker build services/api --tag ask-pesu
```

Running a service directly from a monorepo checkout needs no copy: the loader walks up from
`app/contract.py` and finds the root `conf/collection.yaml` on its own.

## Layout

```
.
├── conf/collection.yaml     # the shared Qdrant contract -- the only copy
├── pyproject.toml           # shared ruff + pytest configuration (no runtime deps)
├── tests/                   # contract tests
├── .pre-commit-config.yaml
└── services/
    ├── api/                 # own README, Dockerfile, deps, app/contract.py
    └── db/                  # own README, Dockerfile, deps, app/contract.py
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
