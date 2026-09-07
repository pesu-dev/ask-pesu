# ask-pesu

A retrieval-augmented question answering system for PES University, answering from
[r/PESU](https://www.reddit.com/r/PESU/) discussions.

This is a monorepo holding both halves of the system: the service that fills the search index,
and the service that answers questions from it. They are deployed as three Hugging Face Spaces —
a production and a development api, and a single db writing the collection both read — which
means one schema contract, shared by everything.

- **Live:** [askpesu](https://pesu-dev-askpesu.hf.space) · **Dev:** [askpesu-dev](https://pesu-dev-askpesu-dev.hf.space)

---

## Contents

- [Services](#services) · [How it works](#how-it-works) · [The streaming protocol](#the-streaming-protocol) · [Where things live](#where-things-live)
- [HTTP API](#http-api) · [The collection contract](#the-collection-contract) · [Creating a collection](#creating-a-collection) · [Why builds copy shared files](#why-builds-copy-shared-files)
- [Repository layout](#repository-layout) · [Dependencies](#dependencies) · [Getting started](#getting-started) · [Environment variables](#environment-variables)
- [Running the services](#running-the-services) · [Backfilling history](#backfilling-history) · [Configuration](#configuration)
- [The frontend](#the-frontend) · [Quota and cooldowns](#quota-and-cooldowns) · [Failure behaviour](#failure-behaviour)
- [Testing](#testing) · [Linting and formatting](#linting-and-formatting) · [Continuous integration](#continuous-integration)
- [Deployment](#deployment) · [Rollback](#rollback) · [Contributing](#contributing) · [Known issues](#known-issues)

---

## Services

| Path | What it does | Spaces |
|---|---|---|
| [`services/api`](services/api) | FastAPI + LangChain RAG backend, and the React frontend it serves | [`askpesu`](https://huggingface.co/spaces/pesu-dev/askpesu) (prod), [`askpesu-dev`](https://huggingface.co/spaces/pesu-dev/askpesu-dev) (dev) |
| [`services/db`](services/db) | Reddit listener that streams new r/PESU comment threads into Qdrant, plus the offline backfill scripts | [`askpesu-db`](https://huggingface.co/spaces/pesu-dev/askpesu-db) — one instance, shared by both api environments |

Each service directory is self-contained and shaped like a repository root — its own
`README.md` carrying that Space's frontmatter, its own `Dockerfile`, its own `app/` package.
Deploy workflows use `git subtree split` to push a single service directory to its Space, so
the Space receives a tree identical to what that service would look like standing alone. This
single fact explains most of the structural decisions below, including why shared files are
copied at deploy time rather than imported.

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
│  walk to root,    │                        │            │                 │
│  render thread    │                        │            ▼                 │
│      │            │                        │  rewrite query w/ history    │
│      ▼            │                        │            ▼                 │
│  embed dense +    │      ┌──────────┐      │  MultiQueryRetriever         │
│  sparse (BM25)    │─────▶│  Qdrant  │◀─────│            ▼                 │
│      │            │      │ 1 coll./ │      │  dense search (k=5)          │
│      ▼            │      │   env    │      │            ▼                 │
│  upsert by UUID   │      └──────────┘      │  cross-encoder rerank        │
└───────────────────┘            ▲           │            ▼                 │
        ▲                        │           │  Qwen3-4B → token stream     │
        │               conf/collection.yaml └──────────────────────────────┘
  scripts/ (backfill)   (the shared contract)
```

### The writer — `services/db`

A daemon thread consumes `subreddit.stream.comments(skip_existing=True)`. For each new comment
it walks up to the thread's root comment, renders the whole thread as indented text with
`anytree`, prefixes the submission title and body, and upserts a single point per root comment.

**The unit of indexing is a thread, not a comment.** A reply like "yes, around 8.5" is
meaningless alone; embedded with its question and the post it hangs off, it is answerable. The
point id is a UUIDv5 of the root comment's Reddit id, so a busy thread is repeatedly
overwritten rather than accumulating near-duplicate points. AutoModerator comments are skipped —
its boilerplate appears on many threads and would otherwise be retrieved for unrelated
questions.

Every point is written with **two vectors**: the dense embedding, and a BM25 sparse vector from
`fastembed`. The reader currently queries dense only. Writing sparse now is what makes turning
on hybrid retrieval a configuration change later instead of re-embedding the whole collection.

A stream only yields comments posted after it opens, so a restart would otherwise leave a
permanent hole — and this service restarts on every promotion. Before opening the stream it
therefore **catches up**: it re-indexes the threads behind the last `CATCH_UP_COMMENTS` comments
(100 by default), deduplicated, since a busy thread contributes many of them and they all resolve
to one point. Writes are upserts keyed by the root comment, so overlapping with the stream costs
an embedding and changes nothing — which is why the window is generous rather than exact. It does
not need to know how long it was down.

The catch-up and the stream share one `index_comment()`, for the same reason the tree renderer is
shared with the backfill: two code paths writing the same thread must not be able to produce
different documents.

It runs once, at startup, not on every reconnect. A reconnect follows a transient error and its
gap is seconds where a restart's is minutes, so re-scanning the backlog on every network blip
would cost far more than it recovered. That leaves a small blind spot by choice: comments posted
during those few seconds are missed, and only a backfill would recover them.

Anything older than that window comes from [the backfill scripts](#backfilling-history).

### The reader — `services/api`

`POST /ask` streams newline-delimited JSON. The pipeline, wired with LangChain Expression
Language in `app/rag.py`:

1. **Rewrite** — the question plus chat history becomes one standalone, retrieval-friendly
   query. This resolves "is it hard?" into "is the Data Structures course at PES University
   hard?" and expands PESU abbreviations (RR, EC, CSE, SGPA…).
2. **Multi-query expansion** — `MultiQueryRetriever` asks the LLM for several phrasings and
   unions what each retrieves, recovering passages a single phrasing would miss.
3. **Dense retrieval** — `k=5` per phrasing against the Qdrant collection, through
   `ScoredRetriever`, which keeps each document's similarity score rather than discarding it.
4. **Rerank** — `cross-encoder/ms-marco-MiniLM-L6-v2` scores every (query, document) pair
   through a sigmoid and drops anything below `score_threshold`. A cross-encoder reads both
   texts together, which a vector search structurally cannot.
5. **Generate** — `Qwen/Qwen3-4B-Instruct-2507` via Hugging Face Inference (`nscale` provider),
   streamed token by token.

Both retrieval-side LLM calls always use the **primary** model, even in thinking mode, so
thinking tokens are never spent reformulating a question.

Step 4 is a filter, not just a sort. If nothing clears the threshold the answer prompt receives
no context and the system prompt makes the model say it does not have that information — an
admission is better than an answer invented from weak context.

**Conversations are never stored server-side.** The frontend keeps them in `localStorage` and
replays the relevant history with each request.

## The streaming protocol

`/ask` returns NDJSON — one complete JSON object per line, so a client can parse incrementally
without buffering the whole response:

| `type` | Meaning |
|---|---|
| `step` | Reasoning text, thinking mode only (the content between `<think>` and `</think>`) |
| `token` | A chunk of the answer |
| `error` | Generation failed; `content` carries the message |
| `done` | Always last, on success and on failure alike |

Two properties worth knowing:

- **The generator never raises.** By the time it runs, the HTTP status and headers are already
  sent, so a failure cannot become a 500. It is reported as an `error` event, and `done` still
  follows, so a client waiting on it never hangs.
- **`</think>` can split across chunks.** The stream arrives in arbitrary pieces, so `"...</thi"`
  and `"nk>..."` can be separate chunks. The backend holds back the last `len("</think>") - 1`
  characters — the longest fragment that could still complete the tag — and emits everything
  before it.

The event shape is duplicated between the backend that emits it and the client that parses it.
Any change must be made in **both** `services/api/app/rag.py` and
`services/api/frontend/src/lib/api.ts`; nothing enforces that they agree.

## HTTP API

### `services/api`

| Route | Body | Returns |
|---|---|---|
| `GET /` | — | The compiled SPA. **503** with a JSON explanation if the frontend was never built |
| `POST /ask` | `{query, thinking?, history?}` | An NDJSON stream — see [The streaming protocol](#the-streaming-protocol). **429** with a quota snapshot if that model is in cooldown |
| `POST /rewriteQuery` | Same model as `/ask`; only `query` is read | `{query}` — the question condensed to at most eight words, for the conversation sidebar |
| `GET /health` | — | `{status, message, timestamp}`. Liveness only: it does not probe Qdrant or the provider, because the startup contract check means a running process already passed those |
| `GET /quota` | — | `{status, quota, timestamp}`, keyed by mode. `next_available` is present only while a model is blocked, so a client can treat its presence as "retry after this" |
| `GET /docs` | — | Swagger UI, generated from the pydantic models in `app/models/` and the examples in `app/docs/` |

`history` is a list of `{query, answer}` turns. Conversations are not stored
server-side, so the client replays what it wants considered. Any turn whose
`query` equals the current one is skipped — clients often include the in-flight
question, and feeding it back as already-answered confuses the rewrite step.

`thinking` selects the thinking model for the answer. Retrieval always uses the
primary model regardless.

Request bodies are validated in strict mode, so a string `"true"` is rejected
rather than coerced to a boolean.

A `/quota` response while the thinking model is in cooldown:

```json
{
  "status": true,
  "quota": {
    "thinking": {"available": false, "next_available": "2026-09-08T12:00:00+05:30"},
    "primary":  {"available": true}
  },
  "timestamp": "2026-09-07T12:00:00+05:30"
}
```

### `services/db`

| Route | Returns |
|---|---|
| `GET /` | A small status page: whether the listener is alive, which collection it writes, and why it stopped if it has. Always **200** |
| `GET /health` | `{"status": "ok"}`, or **503** `{"status": "error", "detail": ...}` once the listener has stopped on a contract violation |

The listener has no other surface; all of its work happens on a background thread. `/` exists
because a Space is rendered at that path, so without it the Space page is a 404 for anyone who
opens it.

The split in status codes is deliberate. `/` is what the platform polls to decide the app is up,
and a contract violation is permanent — answering 503 there could have the Space restarted on a
loop it cannot recover from, and **every restart of this service loses the r/PESU comments posted
while it was down**. So `/` stays 200 and reports the problem in its text; `/health` carries the
503, because it is the endpoint meant to be machine-read.

### Where things live

| To change… | Edit |
|---|---|
| Prompts, model ids, `k`, reranker toggle | `services/api/conf/config.yaml` |
| The retrieval pipeline itself | `services/api/app/rag.py` |
| Routes, CORS, static serving, startup | `services/api/app/app.py` |
| Request/response schemas and OpenAPI examples | `services/api/app/models/`, `services/api/app/docs/` |
| Cooldown behaviour | `services/api/app/quota.py` |
| What gets indexed, and how a thread is rendered | `services/db/app/app.py`, `services/db/app/utils.py` |
| The offline backfill | `services/db/scripts/` |
| Collection name, embedding model, vector geometry, payload keys | `conf/collection.yaml` |
| The streaming event contract | `services/api/app/rag.py` **and** `services/api/frontend/src/lib/api.ts` |

## The collection contract

`services/db` **writes** the Qdrant collection; `services/api` **reads** it. They must agree on
the collection name, embedding model, vector dimensions, distance metric, vector naming and
payload schema. A mismatch corrupts retrieval quietly, so all of it is written down **once**, in
[`conf/collection.yaml`](conf/collection.yaml), and both services load that file.

The collection *name* is deployment configuration (`QDRANT_COLLECTION`), exactly like
`QDRANT_URL`; what the contract fixes is the **shape**.

There is **one db Space**, so there is one deployed collection: `ask-pesu-prod`. The db writes
it and both api Spaces read it, which means the dev api answers from exactly the data
production has — the only way a staging reader can tell you anything useful about a promotion.
The api is a strict reader, so sharing carries no risk of one environment corrupting the other.

`ask-pesu-dev` is the second collection, and it is **not** a deployed environment. It exists so
that running the listener locally, or the CI container smoke tests, cannot write into the live
index. Point local work at it; point deployed services at `ask-pesu-prod`.

| | Value |
|---|---|
| Embedding model | `Alibaba-NLP/gte-modernbert-base` |
| Vector size / distance | 768 / Cosine |
| Dense vector name | `dense` — named, not the unnamed default, so one collection can hold both vectors |
| Sparse vector | `sparse`, `modifier: idf`, from `Qdrant/bm25` — written by the db, not yet queried by the api |
| Payload keys | `root_comment_id`, `post_id`, `author`, `url`, `permalink`, `score`, `upvote_ratio`, `created_utc`, `flair`, `nsfw` |
| Citation target | `permalink` — for a link post `url` is the external article, not the discussion |

It is enforced, not merely documented:

- **The writer** creates the collection from the contract when absent, refuses to write into one
  whose geometry disagrees, and rejects any payload whose key set differs from the contracted
  list. A payload mismatch stops the listener and turns `/health` into a 503 rather than
  retrying — retrying cannot fix a schema bug, and a visibly dead writer beats one quietly
  writing documents the reader cannot use.
- **The reader** refuses to start unless the live collection matches, the loaded embedding model
  is the contracted one at the contracted width, and every payload key it consumes is one the
  contract guarantees. The width is measured by embedding a probe string through the public
  interface, because the two services wrap the underlying model under different attribute names.
- **CI** asserts that every shared file is tracked exactly once, that `requirements.txt` still
  matches `pyproject.toml`, and that the tree each Space would actually receive contains
  everything it needs.

Each service reads the contract through its own small `app/contract.py`. **Change values in
`conf/collection.yaml`, never in a service.**

Two knobs are deliberately absent from the contract. The collection *name* is deployment
configuration, so it comes from the environment and has no default — a default would let a
misconfigured deployment quietly read or write the wrong environment's data. And removing the
`sparse:` block entirely is a supported escape hatch: both services skip the sparse checks when
it is absent, and the writer falls back to dense-only.

### Creating a collection

`services/db` creates the collection from the contract on first start, which is the easiest
path. To create one by hand in Qdrant Cloud instead:

| Field | Value |
|---|---|
| Collection name | `ask-pesu-prod` for the deployed services, `ask-pesu-dev` for local work |
| Dense vector name | `dense` |
| Dimension | `768` |
| Metric | `Cosine` |
| Sparse vector name | `sparse` |
| IDF modifier | **enabled** |

The IDF modifier is the part that is easy to skip and impossible to notice afterwards. Without
it Qdrant scores raw term frequency, so a thread that merely repeats "PESU" outranks one that
answers the question — and nothing errors. Both services check for it at startup and refuse to
run without it.

**Payload indices are not needed.** Nothing filters on payload; retrieval passes only `k` and
`score_threshold`. Unlike vector configuration, indices can be added to a populated collection
at any time, so add one when a filter exists to justify it.

### Why builds copy shared files

Every file both services share lives once, at the repository root: `conf/collection.yaml`,
`requirements.txt`, `pyproject.toml`, `uv.lock`, `LICENSE`, `.env.example`. But each service
deploys with `git subtree split --prefix=services/<name>`, which ships **only that directory** —
the repository root never reaches the running Space.

So the deploy copies four of them into the service tree first: `conf/collection.yaml`,
`requirements.txt`, `LICENSE` and `.env.example`. The workflow refuses to push a tree missing any
of them. The first two are load-bearing — without the contract both services abort at startup,
and without the requirements the image will not build. The other two only need to be *present*
in a published tree, but they are checked identically, because all four come from one copy step
and a missing one means that step went wrong.

`pyproject.toml` and `uv.lock` are never copied: neither Dockerfile reads them, so they have no
reason to reach a Space.

The copies are generated, never committed — `.gitignore` covers them, and CI fails if a second
copy of any shared file is tracked. A committed copy would be a second source that drifts from
the authored one without anything noticing.

Running a service straight from a checkout needs no copy at all: the loader walks up from
`app/contract.py` and finds the root file on its own. Only **Docker builds** need it, because
the build context is the service directory:

```bash
mkdir -p services/api/conf
cp conf/collection.yaml services/api/conf/
cp requirements.txt services/api/
docker build services/api --tag ask-pesu
```

If both copies exist and differ, the loader raises rather than silently preferring the stale one.

## Repository layout

```
.
├── conf/collection.yaml      # the shared Qdrant contract -- the only copy
├── .env.example              # every environment variable, for both services
├── pyproject.toml            # the only pyproject: deps for both services + ruff config
├── requirements.txt          # compiled from it; the only requirements file
├── uv.lock                   # the only lockfile
├── LICENSE                   # the only copy; vendored into each Space at deploy time
├── .python-version           # 3.12
├── .pre-commit-config.yaml
├── scripts/
│   └── check_duplication.py  # asserts the four pairs that must agree, still agree
├── .github/
│   ├── actions/deploy-space/ # the single deploy implementation, shared by both workflows
│   └── workflows/            # CI and deploys
└── services/
    ├── api/
    │   ├── app/
    │   │   ├── app.py        # routes, lifespan, static serving
    │   │   ├── rag.py        # the retrieval + generation pipeline
    │   │   ├── quota.py      # per-model cooldowns
    │   │   ├── contract.py   # reader side of the collection contract
    │   │   ├── models/       # pydantic request/response schemas
    │   │   └── docs/         # OpenAPI examples, one module per route
    │   ├── conf/config.yaml  # prompts, model ids, retrieval knobs
    │   ├── frontend/         # Vite + React 18 + TypeScript + shadcn/ui
    │   ├── .dockerignore     # per-service: Docker reads it from the context root only
    │   ├── Dockerfile        # multi-stage: builds the frontend, then the API
    │   └── README.md         # Space page + frontmatter for askpesu / askpesu-dev
    └── db/
        ├── app/
        │   ├── app.py        # the Reddit listener
        │   ├── utils.py      # thread rendering, shared with the backfill
        │   └── contract.py   # writer side of the collection contract
        ├── scripts/
        │   ├── generate_processed_data.py  # raw dumps -> per-post JSON
        │   └── populate_db.py              # per-post JSON -> Qdrant
        ├── .dockerignore
        ├── Dockerfile
        └── README.md         # Space page + frontmatter for askpesu-db
```

## Dependencies

There is **one** `pyproject.toml` and **one** `requirements.txt`, both at the root. What the two
services share is the base `dependencies`; what only one needs is an extra (`api` / `db`):

```bash
uv pip compile pyproject.toml --extra api --extra db \
    --python-platform linux --python-version 3.12 -o requirements.txt
```

This compiles the **union**, so each image installs a little it does not import — the api
carries `fastembed`/`onnxruntime` (~190 MB), the db carries `langchain-classic` and friends.
That is the price of one file, and it buys something worth having: the embedding stack is
resolved exactly **once**, so the writer and the reader cannot end up on different versions of
the library that produces the vectors. `--python-platform` and `--python-version` are pinned so
the file generated on a laptop is the file the linux/amd64 Space installs.

`torch` is pinned to the `+cpu` build from PyTorch's own index. Both Spaces run on CPU, and the
CUDA wheels were roughly 4 GB of image for libraries that are never loaded. It is declared as a
direct dependency even though only `sentence-transformers` imports it, because uv's index
redirection applies to direct dependencies only.

CI recompiles `requirements.txt` on every push and fails if the committed file differs, so a
dependency edit cannot ship an old resolution to a Space.

## Getting started

**Prerequisites:** Python 3.12, Node.js 24 (what the Dockerfile builds with), and a Qdrant
instance (the free [Qdrant Cloud](https://cloud.qdrant.io/) tier is enough). Docker only if you
want to build images.

```bash
git clone https://github.com/pesu-dev/ask-pesu.git
cd ask-pesu
cp .env.example .env          # then fill it in -- see below
```

The repo targets **Python 3.12 exactly**: `.python-version`, both Dockerfile base images, both
Space `python_version` declarations, ruff's `target-version` and every CI job all say 3.12.

## Environment variables

Copy [`.env.example`](.env.example) to `.env` at the repository root and fill it in. **One root
`.env` serves both services** — `load_dotenv()` searches upwards from the module that calls it,
so running either service from anywhere in the repo picks it up. `.env` is gitignored.

| Variable | Used by | How to get it |
|---|---|---|
| `QDRANT_URL` | api, db | Qdrant Cloud → your cluster → Overview → Endpoint |
| `QDRANT_API_KEY` | api, db | Qdrant Cloud → your cluster → API keys. Must cover the collection below — a JWT scoped elsewhere returns 403. The db needs write access, and manage access if the collection does not exist yet |
| `QDRANT_COLLECTION` | api, db | `ask-pesu-dev` locally; `ask-pesu-prod` on all three Spaces. Required; there is deliberately no default |
| `HF_TOKEN` | api | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) — a **Read** token suffices |
| `REDDIT_CLIENT_ID` | db | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → create a **script** app; the id is the string under the app name |
| `REDDIT_CLIENT_SECRET` | db | Same app, the field labelled **secret** |
| `ENV` | api | Optional. Set to `test` to serve canned responses; see [Running the services](#running-the-services) |
| `ASKPESU_CONFIG_PATH` | api | Optional, and normally set for you: `--config` writes it. Overrides the path to `conf/config.yaml` |

**Write values unquoted.** `python-dotenv` strips surrounding quotes but
`docker run --env-file` does not — it passes the quote characters through as part of the value,
so a quoted URL or key reaches the container malformed.

Both services read the same names, so each secret is declared once. The Space and GitHub secret
names are identical to these.

`HF_TOKEN` is **required** by `services/api`: it is read with `os.environ[...]` and raises
`KeyError` at startup if missing, so the server never binds. It authenticates both the Inference
calls and the download of the embedding and reranker models.

In production nothing reads `.env`; each Space injects the same names from its
**Settings → Secrets**.

## Running the services

### API + frontend

Two terminals. The backend:

```bash
cd services/api
pip install -r ../../requirements.txt
python -m app.app                      # http://localhost:7860
```

Accepts `--host`, `--port`, `--config` and `--debug` (which enables reload and DEBUG logging).
`/docs` serves Swagger UI.

The frontend dev server:

```bash
cd services/api/frontend
npm ci
npm run dev                            # http://localhost:8080
```

Vite proxies `/ask`, `/quota`, `/health` and `/rewriteQuery` to `localhost:7860`, so the two run
together with no CORS configuration. The backend does not need a built frontend for this: it
warns that `frontend/dist` is missing, serves every API route normally, and returns a 503 from
`/` explaining why there is no UI there.

In production there is no proxy and no second server: the Dockerfile builds the frontend and
FastAPI serves `frontend/dist` on the same origin as the API, from port 7860.

**Working on the frontend without credentials.** `ENV=test` swaps the whole pipeline for a
canned NDJSON script — thinking steps, markdown, LaTeX and a Sources list — so no Qdrant, no
`HF_TOKEN` and no inference spend are involved. The RAG pipeline is not built at all in this
mode, and every route still answers in its real shape.

```bash
ENV=test python -m app.app
```

### DB listener

```bash
cd services/db
pip install -r ../../requirements.txt
python -m app.app                      # http://localhost:7860
```

Startup order, and what fails when:

1. Connects to Qdrant and loads the embedding model, checking it produces vectors of the
   contracted width.
2. Creates the collection from the contract if absent; validates it if present.
3. Verifies the Reddit credentials with one cheap read of r/PESU. praw resolves lazily, so
   without this check bad credentials would first surface on the background thread, inside the
   catch-all that treats errors as transient — the listener would retry a 401 forever while
   `/health` reported ok.
4. Starts the listener thread.

Any of the first three failing aborts startup. Once running, `/health` returns
`{"status": "ok"}`, or **503** with a `detail` once the listener has stopped on a contract
violation.

The listener only reacts to **new** comments, so nothing happens until someone posts in r/PESU.

> Against a fresh Qdrant, run `services/db` **before** `services/api`. The writer is what creates
> the collection, and the reader refuses to start without one.

### Docker

```bash
mkdir -p services/api/conf && cp conf/collection.yaml services/api/conf/
cp requirements.txt services/api/
docker build services/api --tag ask-pesu
docker run --rm -p 7860:7860 --env-file .env ask-pesu
```

Substitute `db` for `api` for the listener. Both images install the **CPU build of torch** from
PyTorch's own index, which is what keeps them near 3 GB instead of ~16 GB. Both run as uid 1000,
matching how Hugging Face Spaces run containers.

## Backfilling history

The listener only ever sees comments posted after it starts, so a new collection begins empty.
`services/db/scripts/` is how it gets its history, in two stages.

**1. Reassemble threads from raw dumps.** Input is two JSONL exports of r/PESU, one of posts and
one of comments. For each post, every top-level comment becomes one document containing that
comment and all its replies:

```bash
cd services/db
python scripts/generate_processed_data.py \
    --posts r_r_PESU_posts.jsonl \
    --comments r_r_PESU_comments.jsonl \
    --output-dir processed_data
```

Posts are sharded across worker processes, since rebuilding tens of thousands of comment trees
is CPU-bound. Deleted, removed and AutoModerator comments are pruned. The tree rendering is
imported from `app/utils.py` rather than reimplemented, so a thread backfilled from a dump is
byte-identical to the same thread indexed from the live stream — if those two diverged, the same
discussion would embed differently depending on which path wrote it.

**2. Embed and upsert.** This writes the same shape of point the listener does: same id
derivation, same text layout, same payload keys, same dense and sparse vectors, all read from
the contract.

```bash
python scripts/populate_db.py --data-dir processed_data --dry-run   # check first
python scripts/populate_db.py --data-dir processed_data
```

`--dry-run` validates the collection, parses every input file and checks each payload against
the contract, without building the embedding model or writing anything — everything that can go
wrong cheaply, before the expensive part.

**The dump always wins.** It is a fresh snapshot taken at backfill time, so for any thread it is
at least as complete as what the listener holds: the listener indexes a thread when a comment
arrives and never revisits it, while the snapshot carries every reply up to the moment it was
taken. Anything already stored is therefore re-embedded and replaced, with no opt-out — an
option to keep the older copy could only ever preserve a staler one.

Point ids come from the root comment, so a repeat is an overwrite rather than a duplicate, and
interrupted runs resume: each input file moves to `completed/` only once every document in it is
stored. After the run, every inserted id is read back and any that are missing are written to
`missing_points.json`.

Prefer running the backfill with the listener stopped. Both write by the same id so they
converge rather than conflict, but there is no reason to pay for the same embedding twice.

## Configuration

Runtime behaviour that is *not* part of the collection contract lives in
[`services/api/conf/config.yaml`](services/api/conf/config.yaml):

| Key | Default | Meaning |
|---|---|---|
| `llm.primary.repo_id` | `Qwen/Qwen3-4B-Instruct-2507` | Answers in normal mode; query rewriting and multi-query expansion in **both** modes |
| `llm.thinking.repo_id` | `Qwen/Qwen3-4B-Thinking-2507` | Answers in thinking mode only |
| `llm.*.provider` | `nscale` | Routes the Inference call to a third-party host rather than HF's own hardware |
| `llm.*.temperature` | `0.3` | Sampling temperature; low, to stay close to retrieved threads |
| `llm.*.max_new_tokens` | `2048` | Generation cap. A thinking model spends part of it on reasoning |
| `llm.*.timeout` | `120` | Seconds to wait on the provider before failing the stream |
| `search_kwargs.k` | `5` | Documents retrieved **per generated phrasing**, so the reranker usually sees more than this |
| `search_kwargs.score_threshold` | `0.3` | Minimum relevance, reused as the reranker's cutoff — one knob, not two |
| `reranker.enabled` | `true` | Turning it off skips the torch and sentence-transformers load at startup, and falls back to ranking by vector score |
| `reranker.model` | `cross-encoder/ms-marco-MiniLM-L6-v2` | The cross-encoder |
| `prompts.*` | — | System, answer and query-rewrite prompts |

Prompt and model changes go here first — they are configuration, not code. Anything that would
make already-stored vectors unreadable belongs in `conf/collection.yaml` instead.

`--config` selects a different file. It is passed to the server through the environment, because
uvicorn is started with an import string and therefore imports a fresh copy of the module —
anything attached to the module object that `python -m app.app` is executing would not be seen
by the app uvicorn actually serves.

## The frontend

Vite + React 18 + TypeScript, with shadcn/ui components over Tailwind. It is built by the first
stage of the api Dockerfile and served by FastAPI from the same origin, so the client uses
relative URLs and production needs no CORS configuration.

| Path | What is there |
|---|---|
| `src/lib/api.ts` | The NDJSON client: parses `step`/`token`/`error`/`done` events off the stream |
| `src/lib/chat-store.ts`, `chat-persistence.ts` | Conversation state, persisted to `localStorage` |
| `src/components/chat/` | Message rendering, sources, input, welcome screen, error banner |
| `src/hooks/use-quota.ts`, `use-health.ts` | Poll `/quota` and `/health` so the UI can disable a mode before it is used |
| `src/pages/` | The chat page and a 404 |

```bash
npm run dev     # dev server on 8080, proxying the API routes to 7860
npm run build   # production build into dist/
npm test        # vitest
npm run lint    # eslint
```

## Quota and cooldowns

The inference provider rate-limits, and retrying into a refusal just produces more failures, so
each model carries its own cooldown:

- A quota failure surfaces **mid-stream**, after the response headers are already sent, so it
  cannot become a 429. `generate()` reports it as an `error` event and calls back into
  `QuotaState.disable()`, which blocks that model for 24 hours.
- Subsequent requests for that model are refused **before** streaming starts, as a real 429
  carrying the quota snapshot, so the client can say when to retry and whether the other mode is
  still usable.
- Cooldowns expire lazily: `refresh()` re-enables the model the next time anything looks at it,
  so there is no background task and no window where the state is stale while being read.
- The two models are tracked separately — exhausting thinking mode leaves normal mode usable.

Two properties of this are permanent rather than pending. The state lives in process memory, so a
restart clears it and a second replica would keep its own view — correct for one Space, wrong the
moment there are two. And `_is_quota_error` is a heuristic: an HTTP 429, or one of a handful of
phrases in the message. A false positive costs one unnecessary cooldown; a false negative just
means retrying against a provider that is already refusing us. Neither is worth a fix at this
size, but both are worth knowing before trusting `/quota` as a source of truth.

## Failure behaviour

The system is built to fail loudly at startup and quietly degrade at request time, because the
alternative — answering from the wrong data — is worse than not answering.

| Situation | What happens |
|---|---|
| `QDRANT_COLLECTION` unset | Both services refuse to start. No default, deliberately |
| Collection missing, geometry wrong, or sparse modifier absent | The db creates it if missing; otherwise both services refuse to start, naming the offending value |
| Embedding model produces the wrong width | Both services refuse to start |
| `HF_TOKEN` missing | The api raises `KeyError` before binding a port |
| Reddit credentials missing or rejected | The db refuses to start |
| A payload's keys drift from the contract | The db's listener stops and `/health` returns 503 |
| Reddit or network error in the listener | Treated as transient; the stream is re-entered |
| Provider quota exhausted mid-answer | An `error` event, then a 24-hour cooldown for that model |
| Nothing clears the relevance threshold | The model says it does not have that information |
| Frontend not built | The api warns, serves every API route, and returns 503 from `/` |

## Testing

```bash
cd services/api/frontend
npm test                               # vitest
```

There is no Python test suite. The contract is enforced at runtime instead: both services
validate the live collection, the embedding model and every payload before doing any work, and
refuse to run against a mismatch.

CI checks the structural invariants a running service cannot see — that shared files are
single-sourced, that `requirements.txt` matches `pyproject.toml`, and that the tree each Space
receives is complete. It also runs the one check that behaves like a test:

```bash
python3 scripts/check_duplication.py
```

Four pairs of files must agree and cannot share code, because each side ships somewhere the other
never reaches — a `git subtree split` sends only `services/<name>/`, the frontend is TypeScript,
and Space frontmatter is read before any code runs. The script asserts each pair:

| Pair | How it is checked |
|---|---|
| the two `app/contract.py` loaders | shared definitions compared as ASTs with string literals blanked, so wording may differ but logic may not |
| both writers' payload dicts | keys extracted statically, compared to `conf/collection.yaml` |
| each Space README's `models:`/`preload_from_hub:` | must list the contracted embedding model |
| the NDJSON event names | pydantic `Literal` compared to the frontend's `StreamEvent` union |

The loaders have drifted once already, which is what the first of those exists to prevent.

## Linting and formatting

One ruff configuration in `pyproject.toml` covers both services, with no per-service exemptions.

```bash
pip install pre-commit
pre-commit install                     # run automatically on commit
pre-commit run --all-files             # or on demand
```

`ruff check .` and `ruff format .` from the repository root behave identically to CI, which runs
ruff through the same hooks rather than as a separate job.

## Continuous integration

| Workflow | Trigger | What it does |
|---|---|---|
| `source.yaml` | PR opened/updated | Rejects PRs that are not from a fork, come from a fork's `main`, or target anything other than `dev` |
| `pre-commit.yaml` | Push, PR | Every pre-commit hook, on all files — ruff lint and format included |
| `contract.yaml` | Push, PR | Asserts each shared file is tracked exactly once; recompiles `requirements.txt` and fails on drift; runs [`scripts/check_duplication.py`](scripts/check_duplication.py); rehearses the deploy vendoring and checks each split tree is a complete Space root |
| `docker.yaml` | Push to `dev`, chained off Pre-Commit; or manual | Builds both images, boots each container, polls `/health` |

`docker.yaml` costs roughly twenty minutes per merge, building two ~3 GB images. That is the
price of the only check that exercises a Dockerfile at all — nothing else in CI builds one.
| `deploy-dev-api.yaml` | Push to `dev` | Deploys the api to `askpesu-dev`. The db is not deployed from `dev` |
| `deploy-prod.yaml` | Manual | Fast-forwards `dev` → `main`, then deploys **both** services to `askpesu` and `askpesu-db` |

`deploy-prod.yaml` refuses to run unless `github.actor` is listed in
`vars.PROD_DEPLOYMENT_ALLOWED_USERS`. The dev deploy is not gated — merging to `dev` is the
gate.

Both deploy workflows call one composite action,
[`.github/actions/deploy-space`](.github/actions/deploy-space/action.yml), so the vendoring and
subtree split are written once rather than once per deploy target.

**Required repository secrets:** `HF_TOKEN` (with write scope, to push to the Spaces). The
container smoke tests in `docker.yaml` additionally use `QDRANT_URL`, `QDRANT_API_KEY`,
`REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`, and the optional variable
`QDRANT_COLLECTION_CI` (defaulting to `ask-pesu-dev`, so the smoke tests never write to the
collection the deployed services use).

## Deployment

All three Spaces are fed by force-pushing a `git subtree split` of one service directory, so a
deploy replaces the Space's history. Each deploy job first copies the four shared root files
(`conf/collection.yaml`, `requirements.txt`, `LICENSE`, `.env.example`) into the service tree,
and refuses to push a tree missing any of them.

| Branch | What deploys | To | Collection |
|---|---|---|---|
| `dev` | api only | `askpesu-dev` | `ask-pesu-prod` |
| `main` | api **and** db, unconditionally | `askpesu`, `askpesu-db` | `ask-pesu-prod` |

The dev deploy is **not path-filtered**, deliberately. Skipping a rebuild that could not have
changed anything sounds like a saving, but the deploy job only splits a subtree and pushes —
Hugging Face does the building — and a filter that is ever too narrow means someone merges and
nothing happens, with nothing to say why. A silent skip is the worse failure.

The production deploy has no filter to speak of: GitHub applies `paths` only to `push` and
`pull_request`, and that workflow is `workflow_dispatch` only. What it does choose is to deploy
**both** services on every promotion regardless of what changed, which is what makes "the
production Spaces run `main`" true all the time rather than most of the time.

1. **Merge a PR into `dev`.** `Deploy API to Dev` fires on the push. Confirm `askpesu-dev`
   serves `/health`, `/docs`, the frontend and `/assets`, and streams one real answer. The db is
   not deployed here, so nothing about a writer change is observable at this step.
2. **Dispatch `Deploy to Production`** when dev looks right. It fast-forwards `dev` → `main` —
   aborting if they have diverged rather than inventing a merge nobody reviewed — then deploys
   both services. Confirm `askpesu` as in step 1, and confirm `askpesu-db` serves `/health` with
   its logs showing the listener started. **This is the first time a writer change runs
   anywhere**, so watch it here rather than assuming.

### The db moves only on promotion

There is one db Space, `askpesu-db`, and it writes the collection every reader answers from. It
is deployed by `deploy-prod.yaml` and by nothing else.

The reason is cadence. Merges to `dev` are frequent, and they routinely touch files the db image
consumes — `conf/collection.yaml`, `requirements.txt` — so deploying the writer from `dev` would
restart it often. Each restart is not free: the listener opens its stream with
`skip_existing=True`, so **every r/PESU comment posted while it is down is lost permanently**,
recoverable only by re-running the backfill. Promotions are infrequent and deliberate, which is
the right rhythm for a component whose restarts cost data.

Two consequences, worth internalising rather than discovering:

- **A `services/db` change merged into `dev` is running nowhere.** It ships on the next
  production dispatch, together with whatever else has accumulated. Test writer changes locally
  against `ask-pesu-dev`, and use `populate_db.py --dry-run` before a real backfill.
- **Writer changes reach production unobserved**, because there is no staging writer for them to
  be observed on. What stands in for that is review — `services/db/app/` and
  `services/db/scripts/` require owner review in [`CODEOWNERS`](.github/CODEOWNERS) — and the
  contract, which catches the structural failures at startup: a payload whose keys drift stops
  the listener and turns `/health` into a 503 before anything is stored, and a wrong embedding
  model, vector geometry or credential aborts startup outright.

The failure neither catches is a write that is schema-valid but semantically wrong — a broken
thread rendering, say — which lands silently and is undone only by re-running the backfill. Watch
the db Space's logs and `/health` immediately after a promotion; that is the moment a writer
change first runs anywhere.

**The dev api runs `dev`; the prod api runs `main`.** The production deploy does *not* redeploy
the dev api: `dev` is normally ahead of `main`, so re-pushing `main` over it would silently roll
it back — every deploy here is a force push, so nothing would object.

### Space configuration

Each Space needs its own secrets under **Settings → Variables and secrets**, using exactly the
names in [Environment variables](#environment-variables):

| Space | Secrets | `QDRANT_COLLECTION` |
|---|---|---|
| `askpesu` | `HF_TOKEN`, `QDRANT_URL`, `QDRANT_API_KEY` | `ask-pesu-prod` |
| `askpesu-dev` | `HF_TOKEN`, `QDRANT_URL`, `QDRANT_API_KEY` | `ask-pesu-prod` |
| `askpesu-db` | `QDRANT_URL`, `QDRANT_API_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | `ask-pesu-prod` |

All three are **Docker** SDK Spaces with hardware allocated. The SDK comes from each service
README's frontmatter, but hardware does not — a Space converted from another SDK needs it
assigned in its settings.

All three take the **same** collection. Each verifies the shape of whatever it is pointed at,
but none can detect that another was pointed somewhere else — an api left on `ask-pesu-dev`
would start happily and simply never see anything the writer stores. The db's key needs write
access — and manage access if the collection does not exist yet, since it creates one — while
the two api keys need only read.

> **Bootstrapping a new environment needs care, because the two deploys are on different
> triggers.** `services/api` refuses to start without a contract-conforming collection, and
> `services/db` is what creates one — but the api deploys on a merge to `dev` while the db only
> deploys on a promotion. Point an api at a collection that does not exist yet and it will fail
> to start, and merging again will not fix it. Create the collection first: either run
> `services/db` locally against it once, make it by hand with the geometry in
> [Creating a collection](#creating-a-collection), or promote to production before relying on
> the dev api. This does not arise on an ordinary deploy, only when adding an environment.

### Rollback

Every deploy is a force-push, so rolling back is re-pushing a known-good tree:

```bash
git subtree split --prefix=services/api <good-sha> -b rollback
git push https://pesu-dev:$HF_TOKEN@huggingface.co/spaces/pesu-dev/askpesu rollback:main --force
```

Note the split tree must still carry the vendored files; take `<good-sha>` from a commit whose
deploy succeeded, and vendor them again before splitting if you are building the tree by hand.

On GitHub, revert the merge commit on `dev`. `main` only advances via the production workflow,
so it stays put until the next dispatch.

## Contributing

Pull requests **must** come from a fork and **must** target `dev`; `source.yaml` enforces both.
`main` is a deploy artifact and is advanced only by the production workflow. See
[`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) and
[`.github/CODE_OF_CONDUCT.md`](.github/CODE_OF_CONDUCT.md).

Before opening a PR: `pre-commit run --all-files`.

Reviewers are assigned by [`.github/CODEOWNERS`](.github/CODEOWNERS). Changes to
`conf/collection.yaml` affect both services and always require owner review.

## Known issues

Only work that is actually pending lives here. Deliberate limits are documented where the
subsystem is explained, rather than collected as though someone intends to fix them.

- **Retrieval is dense-only while writes are hybrid.** Every point carries a BM25 sparse vector
  that nothing queries. Switching the reader to `RetrievalMode.HYBRID` is a change to one
  constructor rather than a re-index, but it is not free: Qdrant fuses the two rankings with
  Reciprocal Rank Fusion, whose output is a rank-derived score on a different scale from cosine
  similarity, so `score_threshold` would stop meaning anything and the reranker cutoff would need
  re-deriving against real queries. Planned as its own change.

## License

[MIT](LICENSE).
