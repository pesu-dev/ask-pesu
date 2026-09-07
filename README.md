# ask-pesu

A retrieval-augmented question answering system for PES University, answering from
[r/PESU](https://www.reddit.com/r/PESU/) discussions.

This is a monorepo containing both halves of the system. They are deployed as three separate
Hugging Face Spaces but share one Qdrant collection, and therefore one schema contract.

- **Live:** [askpesu](https://pesu-dev-askpesu.hf.space) · **Staging:** [askpesu-dev](https://pesu-dev-askpesu-dev.hf.space)

---

## Contents

- [Services](#services) · [How it works](#how-it-works) · [Where things live](#where-things-live)
- [Quota and cooldowns](#quota-and-cooldowns) · [The collection contract](#the-collection-contract) · [Repository layout](#repository-layout)
- [Getting started](#getting-started) · [Environment variables](#environment-variables) · [Running the services](#running-the-services)
- [Configuration](#configuration) · [Testing](#testing) · [Linting and formatting](#linting-and-formatting)
- [Continuous integration](#continuous-integration) · [Deployment](#deployment) · [Contributing](#contributing) · [Known issues](#known-issues)

---

## Services

| Path | What it does | Space |
|---|---|---|
| [`services/api`](services/api) | FastAPI + LangChain RAG backend, and the React frontend it serves | [`askpesu`](https://huggingface.co/spaces/pesu-dev/askpesu) (prod), [`askpesu-dev`](https://huggingface.co/spaces/pesu-dev/askpesu-dev) (staging) |
| [`services/db`](services/db) | Reddit listener that streams new r/PESU comment threads into Qdrant | [`askpesu-db`](https://huggingface.co/spaces/pesu-dev/askpesu-db) |

Each service directory is self-contained and shaped like a repository root — its own
`README.md` (carrying that Space's frontmatter), `Dockerfile`, and dependencies. Deploy
workflows use `git subtree split` to push a single service directory to its Space, so the
Space receives a tree identical to what that service would look like standing alone.

## How it works

```
      r/PESU                                            browser
        │                                                  │
        ▼                                                  ▼
┌───────────────────┐                        ┌──────────────────────────────┐
│   services/db     │                        │        services/api          │
│                   │                        │                              │
│  praw comment     │                        │  React SPA (same origin)     │
│  stream           │                        │            │                 │
│      │            │                        │            ▼                 │
│      ▼            │                        │  POST /ask  (NDJSON stream)  │
│  build thread     │                        │            │                 │
│  string + payload │                        │            ▼                 │
│      │            │                        │  rewrite query w/ history    │
│      ▼            │                        │            ▼                 │
│  embed (gte-      │      ┌──────────┐      │  MultiQueryRetriever         │
│  modernbert-base) │─────▶│  Qdrant  │◀─────│            ▼                 │
│      │            │      │ ask-pesu │      │  dense search (k=5)          │
│      ▼            │      └──────────┘      │            ▼                 │
│  upsert by UUID   │            ▲           │  cross-encoder rerank        │
└───────────────────┘            │           │            ▼                 │
                                 │           │  Qwen3-4B → token stream     │
                        conf/collection.yaml └──────────────────────────────┘
                        (the shared contract)
```

**Writer (`services/db`).** A daemon thread consumes `subreddit.stream.comments(skip_existing=True)`.
For each new comment it walks up to the thread's root comment, renders the whole thread as
indented text (`anytree`), prefixes the submission title and body, and upserts a single point
per root comment. The point id is a UUIDv5 of the Reddit comment id, so re-processing a thread
overwrites rather than duplicates it. AutoModerator comments are skipped.

**Reader (`services/api`).** `/ask` streams newline-delimited JSON. The pipeline:

1. **Rewrite** — the user's question plus chat history is rewritten into a standalone,
   retrieval-optimised query. PESU abbreviations (RR, EC, CSE, SGPA, …) are expanded here.
2. **Multi-query expansion** — `MultiQueryRetriever` generates several phrasings and unions
   their results.
3. **Dense retrieval** — `k=5` per generated query against the Qdrant collection.
4. **Rerank** — a `cross-encoder/ms-marco-MiniLM-L-6-v2` scores each (query, document) pair
   through a sigmoid and drops anything below `score_threshold`.
5. **Generate** — `Qwen/Qwen3-4B-Instruct-2507` via Hugging Face Inference (`nscale` provider),
   streamed token by token.

Both retrieval steps always use the **primary** model, never the thinking model, so thinking
mode never spends its tokens on query rewriting.

**Streaming protocol.** `/ask` returns NDJSON, one JSON object per line:

| `type` | Meaning |
|---|---|
| `step` | Reasoning text, emitted only in thinking mode (content between `<think>` and `</think>`) |
| `token` | A chunk of the answer |
| `done` | Stream finished |
| `error` | Generation failed; `content` carries the message |

In thinking mode the backend splits `<think>…</think>` out of the model's output and re-emits
it as `step` events. Any change here must be made in **both** `services/api/app/rag.py` and
`services/api/frontend/src/lib/api.ts`.

**Conversations are never stored server-side.** The frontend keeps them in `localStorage`
under `askpesu-conversations`, and replays the relevant history with each request.

### Where things live

| To change… | Edit |
|---|---|
| Prompts, model ids, `k`, reranker toggle | `services/api/conf/config.yaml` |
| The retrieval pipeline itself | `services/api/app/rag.py` |
| Routes, CORS, static serving, startup | `services/api/app/app.py` |
| Request/response schemas and OpenAPI examples | `services/api/app/models/`, `services/api/app/docs/` |
| Cooldown behaviour | `services/api/app/quota.py` |
| What gets indexed, and how a thread is rendered | `services/db/app/app.py`, `services/db/app/utils.py` |
| Collection name, embedding model, vector geometry, payload keys | `conf/collection.yaml` |
| The streaming event contract | `services/api/app/rag.py` **and** `services/api/frontend/src/lib/api.ts` |

The last row is the one to be careful with: the event shape is duplicated between the backend
that emits it and the client that parses it, and nothing enforces that they agree.

## Quota and cooldowns

The inference provider rate-limits, and retrying into a refusal just produces more failures, so
each model carries its own cooldown:

- A quota failure surfaces **mid-stream**, after the response headers are already sent, so it
  cannot become a 429. `generate()` reports it as an `error` event and calls back into
  `QuotaState.disable()`, which blocks that model for 24 hours.
- Subsequent requests for that model are refused **before** streaming starts, as a real 429
  carrying the quota snapshot, so the client can say when to retry.
- Cooldowns expire lazily: `refresh()` re-enables the model the next time anything looks at it,
  so there is no background task.
- The two models are tracked separately — exhausting thinking mode leaves normal mode usable.

## The collection contract

`services/db` **writes** the Qdrant collection; `services/api` **reads** it. They must agree on
the collection name, embedding model, vector dimensions, distance metric, vector naming, and
payload schema. A mismatch corrupts retrieval quietly, so all of it is written down **once**, in
[`conf/collection.yaml`](conf/collection.yaml), and both services load that file:

One Qdrant cluster holds one collection per environment — `ask-pesu-prod` and `ask-pesu-dev` —
so the collection *name* is deployment configuration (`QDRANT_COLLECTION`), like `QDRANT_URL`.
What the contract fixes is the **shape**, which must be identical everywhere or dev tests
nothing meaningful:

| | Value |
|---|---|
| Embedding model | `Alibaba-NLP/gte-modernbert-base` |
| Vector size / distance | 768 / Cosine |
| Vector name | `dense` (named, so hybrid retrieval can be added without re-indexing) |
| Sparse vector | `sparse`, `modifier: idf` — contracted and verified, unused until hybrid lands |
| Payload keys | `root_comment_id`, `post_id`, `author`, `url`, `permalink`, `score`, `upvote_ratio`, `created_utc`, `flair`, `nsfw` |
| Citation target | `permalink` — for a link post `url` is the external article, not the discussion |

It is enforced, not just documented:

- **The writer** creates the collection from the contract, refuses to write into one whose
  geometry disagrees, and rejects any payload whose key set differs from the contracted list.
  A payload mismatch stops the listener and flips `/health` to 503 rather than retrying.
- **The reader** refuses to start unless the live collection matches, the loaded embedding
  model is the contracted one at the contracted width, and every payload key it consumes is
  one the contract guarantees is written.
- **CI** checks all of it in [`tests/test_contract.py`](tests/test_contract.py), asserts
  `conf/collection.yaml` is the only contract file tracked in git, and asserts the Space
  frontmatter's `models:`/`preload_from_hub:` still name the contracted model.

Each service reads it through its own small `app/contract.py`. **Change values in `conf/`,
never in a service.**

### Creating the collection

`services/db` creates it from the contract on first start, but doing it by hand adds the sparse
vector that hybrid retrieval will need. In Qdrant Cloud:

| Field | Value |
|---|---|
| Collection name | `ask-pesu-prod` and `ask-pesu-dev` — create both, identically |
| Dense vector name | `dense` |
| Dimension | `768` |
| Metric | `Cosine` |
| Sparse vector name | `sparse` |
| IDF modifier | **enabled** — startup validation now rejects a collection without it |

Create the sparse vector even though nothing uses it yet: BM25 needs the `idf` modifier to
weight rare terms, and adding a vector to an existing collection may mean rebuilding it. The
writer validates the dense vector on startup and ignores the sparse one, so the extra vector is
harmless until hybrid lands.

**Payload indices are not needed.** Nothing filters on payload — retrieval passes only `k` and
`score_threshold` — and unlike vector configuration, indices can be added to a populated
collection at any time. Add one only when a filter actually exists to justify it.

### Why builds copy it

`conf/collection.yaml` lives at the repo root, but each service is deployed with
`git subtree split --prefix=services/<name>`, which ships **only that directory** — the repo root
never reaches the running Space. So image builds and deploys copy the file into
`services/<name>/conf/` first, and the deploy workflows refuse to push a tree that lacks it.

That copy is generated, never committed (`.gitignore` covers it). Running a service directly
from a checkout needs no copy — the loader walks up from `app/contract.py` and finds the root
file on its own. Only **Docker builds** need it, because the build context is the service
directory:

```bash
mkdir -p services/api/conf && cp conf/collection.yaml services/api/conf/
docker build services/api --tag ask-pesu
```

If both copies exist and differ, the loader raises rather than silently preferring the stale one.

## Repository layout

```
.
├── conf/collection.yaml      # the shared Qdrant contract -- the only copy
├── .env.example              # every environment variable, for both services
├── pyproject.toml            # shared ruff + pytest config (declares no [project])
├── tests/                    # contract tests
├── .pre-commit-config.yaml
├── .github/workflows/        # CI and deploys
└── services/
    ├── api/
    │   ├── app/              # app.py (routes), rag.py (pipeline), quota.py,
    │   │                     # contract.py, models/ (pydantic), docs/ (OpenAPI)
    │   ├── conf/config.yaml  # prompts, model ids, retrieval knobs
    │   ├── frontend/         # Vite + React 18 + TypeScript + shadcn/ui
    │   ├── Dockerfile        # multi-stage: builds the frontend, then the API
    │   └── README.md         # Space frontmatter for askpesu / askpesu-dev
    └── db/
        ├── app/              # app.py (listener), utils.py, contract.py
        ├── Dockerfile
        └── README.md         # Space frontmatter for askpesu-db
```

The root `pyproject.toml` deliberately declares **no `[project]` table**. It exists so ruff and
pytest resolve one configuration for the whole repo: ruff walks up from each file to the nearest
`pyproject.toml` containing a `[tool.ruff]` table, and the service pyprojects have none.

## Getting started

**Prerequisites:** Python 3.12, Node.js 24 (what the Dockerfile builds with), and a Qdrant instance (the free
[Qdrant Cloud](https://cloud.qdrant.io/) tier is enough). Docker only if you want to build images.

```bash
git clone https://github.com/pesu-dev/ask-pesu.git
cd ask-pesu
cp .env.example .env          # then fill it in -- see below
```

The repo targets **Python 3.12 exactly**: `.python-version`, both Dockerfile base images, both
Space `python_version` declarations, ruff's `target-version` and CI all say 3.12.

## Environment variables

Copy [`.env.example`](.env.example) to `.env` at the repository root and fill it in. **One root
`.env` serves both services** — `load_dotenv()` searches upwards from the module that calls it,
so running either service from anywhere in the repo picks it up. `.env` is gitignored.

| Variable | Used by | How to get it |
|---|---|---|
| `QDRANT_URL` | api, db | Qdrant Cloud → your cluster → Overview → Endpoint |
| `QDRANT_API_KEY` | api, db | Qdrant Cloud → your cluster → API keys. Must be **scoped to the collection below** — a JWT scoped elsewhere returns 403 |
| `QDRANT_COLLECTION` | api, db | `ask-pesu-dev` locally and on staging, `ask-pesu-prod` in production. Required; there is deliberately no default |
| `HF_TOKEN` | api | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) — a **Read** token suffices |
| `REDDIT_CLIENT_ID` | db | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → create a **script** app; the id is the string under the app name |
| `REDDIT_CLIENT_SECRET` | db | Same app, the field labelled **secret** |
| `ENV` | api | Optional. Set to `test` to stream a canned answer instead of calling the LLM |

Both services read the same names, so each secret is declared exactly once. The Space and
GitHub secret names are identical to these.

`HF_TOKEN` is **required**: `services/api` reads it with `os.environ[...]` and raises `KeyError`
at startup if it is missing, so the server never binds. It authenticates both the Inference
calls and the download of the embedding and reranker models.

In production nothing reads `.env`; each Space injects the same names from its
**Settings → Secrets**.

## Running the services

### API + frontend

Two terminals. The backend:

```bash
cd services/api
pip install -r requirements.txt
python -m app.app                      # http://localhost:7860
```

Accepts `--host`, `--port`, `--config`, and `--debug` (debug enables reload and DEBUG logging).
`/docs` serves Swagger UI.

The frontend dev server:

```bash
cd services/api/frontend
npm ci
npm run dev                            # http://localhost:8080
```

Vite proxies `/ask`, `/quota`, `/health` and `/rewriteQuery` to `localhost:7860`, so the two
run together with no CORS configuration.

In production there is no proxy and no second server: the Dockerfile builds the frontend and
FastAPI serves `frontend/dist` on the same origin as the API, from port 7860.

### DB listener

```bash
cd services/db
pip install -r requirements.txt
python -m app.app                      # http://localhost:7860
```

On startup it creates the Qdrant collection from the contract if absent, validates it if
present, then starts the listener thread. It only reacts to **new** comments
(`skip_existing=True`), so nothing happens until someone posts in r/PESU.

`/health` returns `{"status": "ok"}`, or **503** with a `detail` once the listener has stopped
on a contract violation — a dead writer is visible rather than silent.

> Run `services/db` **before** `services/api` against a fresh Qdrant. The writer is what creates
> the collection, and the reader refuses to start without one.

### Docker

```bash
mkdir -p services/api/conf && cp conf/collection.yaml services/api/conf/
docker build services/api --tag ask-pesu
docker run --rm -p 7860:7860 --env-file .env ask-pesu
```

Substitute `db` for `api` for the listener. Both images pull the **CPU build of torch** from
PyTorch's own index, which is what keeps them at ~2.8 GB instead of ~16 GB; the Dockerfiles pass
`--extra-index-url https://download.pytorch.org/whl/cpu` for that reason.

## Configuration

Runtime behaviour that is *not* part of the collection contract lives in
[`services/api/conf/config.yaml`](services/api/conf/config.yaml):

| Key | Default | Meaning |
|---|---|---|
| `llm.primary.repo_id` | `Qwen/Qwen3-4B-Instruct-2507` | Answers, query rewriting, multi-query expansion |
| `llm.thinking.repo_id` | `Qwen/Qwen3-4B-Thinking-2507` | Answers in thinking mode only |
| `llm.*.temperature` | `0.3` | Sampling temperature |
| `llm.*.max_new_tokens` | `2048` | Generation cap |
| `search_kwargs.k` | `5` | Documents retrieved per generated query |
| `search_kwargs.score_threshold` | `0.3` | Reranker cutoff (sigmoid) |
| `reranker.enabled` | `true` | Turn the cross-encoder off to fall back to raw vector scores |
| `prompts.*` | — | System, answer, and query-rewrite prompts |

Prompt and model changes go here first — they are config, not code.

## Testing

```bash
pip install pytest pyyaml qdrant-client langchain-core
pytest tests/ -q
```

The contract suite deliberately avoids the api's torch and LangChain stack so it stays fast. It
runs the shared assertions against **both** services' loaders, and AST-compares their shared
functions so the two cannot drift in behaviour even though each carries its own copy.

Frontend:

```bash
cd services/api/frontend
npm test                               # vitest
```

## Linting and formatting

One ruff configuration covers both services and the tests, with no per-service exemptions.

```bash
pip install pre-commit
pre-commit install                     # run automatically on commit
pre-commit run --all-files             # or on demand
```

`ruff check .` and `ruff format .` from the repository root behave identically to CI.

## Continuous integration

| Workflow | Trigger | What it does |
|---|---|---|
| `source.yaml` | PR opened/updated | Rejects PRs that are not from a fork or that target anything other than `dev` |
| `lint.yaml` | Push (not `main`/`dev`), PR | `ruff check` + `ruff format --check` |
| `pre-commit.yaml` | Push, PR | Every pre-commit hook, on all files |
| `contract.yaml` | Push, PR | Contract tests; asserts one tracked `collection.yaml`; rehearses the deploy vendoring and checks each split tree ships the contract |
| `docker.yaml` | Manual, or after Pre-Commit | Builds both images, boots each container, polls `/health` |
| `deploy-dev.yaml` | Push to `dev` | Deploys **both** services to `askpesu-dev` and `askpesu-db-dev` |
| `deploy-prod.yaml` | Manual | Fast-forwards `dev` → `main`, then deploys **both** services to `askpesu` and `askpesu-db` |

`deploy-prod.yaml` refuses to run unless `github.actor` is listed in
`vars.PROD_DEPLOYMENT_ALLOWED_USERS`. `deploy-dev.yaml` is not gated — merging to `dev` is the
gate.

Both call one composite action, [`.github/actions/deploy-space`](.github/actions/deploy-space/action.yml),
so the vendoring and subtree split exist once rather than once per service per environment.

**Required repository secrets:** `HF_TOKEN`, `QDRANT_URL`, `QDRANT_API_KEY`, `REDDIT_CLIENT_ID`,
`REDDIT_CLIENT_SECRET`.

## Deployment

All three Spaces are fed by force-pushing a `git subtree split` of one service directory, so a
deploy replaces the Space's history. Each deploy job first copies `conf/collection.yaml` into the
service tree and refuses to push a tree without it.

Each Space needs its own secrets set under **Settings → Variables and secrets**, using exactly
the names in [Environment variables](#environment-variables):

| Space | Secrets | `QDRANT_COLLECTION` |
|---|---|---|
| `askpesu` (prod) | `HF_TOKEN`, `QDRANT_URL`, `QDRANT_API_KEY` | `ask-pesu-prod` |
| `askpesu-dev` (staging) | `HF_TOKEN`, `QDRANT_URL`, `QDRANT_API_KEY` | `ask-pesu-dev` |
| `askpesu-db` | `QDRANT_URL`, `QDRANT_API_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | `ask-pesu-prod` |

Both services in one environment must be given the **same** collection. Each verifies the shape
of whatever it is pointed at, but neither can detect that the other was pointed somewhere else —
so an api on `ask-pesu-prod` and a db on `ask-pesu-dev` would both start happily and never
share a document. The API key must be scoped to the collection it is used with.

Note the db has only one Space, so it writes the **production** collection. Nothing currently
populates `ask-pesu-dev` — see the deployment-strategy TODO.

**The dev Spaces run `dev`; the prod Spaces run `main`.** Nothing else writes to them. In
particular the production deploy does *not* redeploy dev: `dev` is normally ahead of `main`, so
re-pushing `main` over the dev Spaces would silently roll them back — every deploy here is a
force push, so nothing would object.

| Branch | Deploys to | Collection |
|---|---|---|
| `dev` | `askpesu-dev`, `askpesu-db-dev` | `ask-pesu-dev` |
| `main` | `askpesu`, `askpesu-db` | `ask-pesu-prod` |

1. **Merge a PR into `dev`.** `Deploy to Dev` fires on the push and deploys both services.
   Confirm `askpesu-dev` serves `/health`, `/docs`, the frontend and `/assets`, and streams one
   real answer; confirm `askpesu-db-dev` serves `/health` and its logs show the listener started.
2. **Dispatch `Deploy to Production`** when dev looks right. It fast-forwards `dev` → `main` —
   aborting if they have diverged, rather than inventing a merge — then deploys both services to
   the production Spaces.

> On a **brand-new** collection the writer has to start before the reader: `services/api`
> refuses to start without a contract-conforming collection, and `services/db` is what creates
> it. Both collections already exist and pass the contract, so this only matters if you add a
> third environment.

### Rollback

Every deploy is a force-push, so rolling back is re-pushing a known-good tree:

```bash
git subtree split --prefix=services/api <good-sha> -b rollback
git push https://pesu-dev:$HF_TOKEN@huggingface.co/spaces/pesu-dev/askpesu rollback:main --force
```

On GitHub, revert the merge commit on `dev`. `main` only advances via the production workflow,
so it stays put until the next dispatch.

## Contributing

Pull requests **must** come from a fork and **must** target `dev`; `source.yaml` enforces both.
`main` is a deploy artifact and is advanced only by the production workflow. See
[`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) and
[`.github/CODE_OF_CONDUCT.md`](.github/CODE_OF_CONDUCT.md).

Before opening a PR: `pre-commit run --all-files` and `pytest tests/ -q`.

Reviewers are assigned by [`.github/CODEOWNERS`](.github/CODEOWNERS). Changes to
`conf/collection.yaml` affect both services and always require owner review.

## Known issues

- **`Docker Container Build` effectively never runs.** Its `workflow_run` trigger has never
  fired (the successful Pre-Commit runs are on fork PR branches), and nothing chains off it now
  that `deploy-dev.yaml` triggers directly on pushes. So the container smoke tests only happen
  on manual dispatch. Switching it to `push: branches: [dev]` would make them real again.
- **Cooldown state is per process.** `QuotaState` lives in memory, so a restart clears it and
  two replicas would each track their own view. Fine for a single Space; wrong the moment there
  is more than one.
- **Quota detection is a heuristic.** `_is_quota_error` matches an HTTP 429 or a handful of
  phrases. A false positive costs one unnecessary cooldown; a false negative just means the
  old behaviour of retrying against a provider that is refusing us.
- **No `.dockerignore`.** A locally built image can bake a `.env` sitting in a service
  directory. Not a deploy risk: the documented `.env` lives at the repository root, which is
  outside both build contexts, and it is gitignored so it never reaches a Space.

## License

[MIT](LICENSE).
