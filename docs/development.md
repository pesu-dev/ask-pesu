# Development

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs Python 3.12 itself.
- Node.js 24, for frontend work. The Dockerfile builds with it.
- Access to Qdrant, unless you only work on the frontend with `ENV=test`. Contributors get a
  read-only key to `ask-pesu-prod`; see
  [collections and keys](collection-contract.md#collections-and-keys).
- Docker, only to build the images.

The repository targets Python 3.12: `.python-version`, both Dockerfiles, both Space frontmatters,
ruff's `target-version` and every CI job use it.

```bash
git clone https://github.com/<your-fork>/ask-pesu.git
cd ask-pesu
uv sync --extra api --extra db
cp .env.example .env    # then fill it in; see configuration.md
```

## Dependencies

**Install with `uv sync` only.** From the repository root, one command installs both services and
every tool:

```bash
uv sync --extra api --extra db
```

It installs from the committed `uv.lock`, so every contributor gets the same versions.

| What | Where it comes from |
|---|---|
| Both services' libraries | The base `dependencies` and the `api` and `db` extras |
| `pre-commit`, `ruff` | The `dev` group, installed by default |
| torch, CPU build | The `cpu` group, installed by default, from PyTorch's CPU index |

Run commands with `uv run`. It finds the root environment from any directory in the repository:

```bash
uv run python -m app.app
uv run ruff check .
```

`uv run` syncs the environment first. It does not remove the extras, but it does reinstall a
default group you excluded, which matters for [the GPU backfill](ingestion.md#using-a-gpu).

**Do not install `requirements.txt` locally.** It is compiled for the Space images, has no `dev`
group, and installing it correctly needs the PyTorch CPU index added by hand.

### Changing a dependency

There is one `pyproject.toml` and one `requirements.txt`, both at the root. What both services
need goes in the base `dependencies`; what one service needs goes in its extra (`api` or `db`).
After editing `pyproject.toml`, run `uv lock` and recompile `requirements.txt`:

```bash
uv pip compile pyproject.toml --extra api --extra db --group cpu \
    --python-platform linux --python-version 3.12 -o requirements.txt
```

- **This compiles both extras into one file**, so each image installs some packages it does not
  import. The writer and the reader then use the same resolved version of the embedding stack.
- **`--group cpu` is required.** torch is in a dependency group, not in `dependencies`. Without the
  flag, torch resolves from PyPI as the much larger CUDA build.
- **`--python-platform` and `--python-version`** make the file match the linux/amd64 Space
  whatever machine compiles it.

CI recompiles the file with this command and fails if the result differs from the committed one.

## Running the services

### API and frontend

The backend:

```bash
cd services/api
uv run python -m app.app               # http://localhost:7860
```

It accepts `--host`, `--port`, `--config` and `--debug` (auto-reload and DEBUG logging). `/docs`
serves Swagger UI.

The frontend dev server, in a second terminal:

```bash
cd services/api/frontend
npm ci
npm run dev                            # http://localhost:8080
```

Vite proxies the API routes to `localhost:7860`. Without a frontend build, the backend logs a
warning, serves every API route, and returns a 503 from `/`. In production the Dockerfile builds
the frontend and FastAPI serves it on port 7860.

Against a new, empty Qdrant, run `services/db` once first. It creates the collection, and the api
refuses to start without one.

### Working without credentials

`ENV=test` replaces the pipeline with a canned stream: sources, reasoning steps, and an answer with
markdown and LaTeX. It needs no Qdrant, no `HF_TOKEN` and no inference credits. The pipeline is
not built, and every route answers in its real shape.

```bash
ENV=test uv run python -m app.app
```

### Answering from a local ollama

`LLM_MODE=ollama` sends every LLM call to a local [ollama](https://ollama.com) server instead of
Hugging Face Inference. Both configured models are published for ollama:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
ollama pull qwen3:4b-thinking-2507-q4_K_M

LLM_MODE=ollama \
OLLAMA_BASE_URL=http://localhost:11434 \
OLLAMA_PRIMARY_MODEL=qwen3:4b-instruct-2507-q4_K_M \
OLLAMA_THINKING_MODEL=qwen3:4b-thinking-2507-q4_K_M \
uv run python -m app.app
```

- **Only the LLM changes.** Qdrant, the embeddings, the reranker, ranking and the prompts are the
  real ones. `HF_TOKEN` is still required.
- **Answers differ from production's**, because the ollama tags are quantised copies. Use it to
  compare the effect of a change, not to judge absolute quality.
- **Thinking mode works.** ollama returns reasoning in a separate field, and `app/local_llm.py`
  puts it back into `<think>` tags.
- **Startup fails** if the server is not running or a model was not pulled, naming the fix.
- **`OLLAMA_NUM_CTX`** (16384 by default) must hold the system prompt, the retrieved threads and
  the answer budget. ollama refuses a longer prompt. Lower it if the model does not fit in VRAM;
  the part that does not fit then runs on the CPU, more slowly.
- **Generation is slower** than the provider, and `limits.timeout_seconds` still bounds the
  request. Raise it locally if answers stop with the timeout error.

### DB listener

The listener writes, so point it at `ask-pesu-dev` with a read-write key from the codeowners.

```bash
cd services/db
uv run python -m app.app               # http://localhost:7860
```

On startup it:

1. connects to Qdrant and loads the embedding model, checking its width against the contract;
2. creates the collection from the contract if it is missing, or validates it;
3. checks the Reddit credentials with one read of r/PESU;
4. starts the listener thread, which catches up on recent comments and then streams.

Any of the first three failing stops startup. The listener only reacts to new comments, so it
writes nothing until someone comments on r/PESU, apart from the catch-up. See
[ingestion.md](ingestion.md#the-listener).

### Docker

The build context is the service directory, so copy the shared files in first (see
[shared files and vendoring](collection-contract.md#shared-files-and-vendoring)):

```bash
mkdir -p services/api/conf && cp conf/collection.yaml services/api/conf/
cp requirements.txt services/api/
docker build services/api --tag ask-pesu
docker run --rm -p 7860:7860 --env-file .env ask-pesu
```

Replace `api` with `db` for the listener. Both images install the CPU build of torch and run as uid
1000, as Hugging Face Spaces do.

To use a local ollama from the container on Linux, share the host's network. `localhost` inside a
container is the container, and ollama listens on the host's loopback only:

```bash
docker run --rm --network host --env-file .env \
  -e LLM_MODE=ollama \
  -e OLLAMA_BASE_URL=http://localhost:11434 \
  -e OLLAMA_PRIMARY_MODEL=qwen3:4b-instruct-2507-q4_K_M \
  -e OLLAMA_THINKING_MODEL=qwen3:4b-thinking-2507-q4_K_M \
  ask-pesu
```

`--network host` is Linux only. On other platforms, ollama has to listen beyond loopback
(`OLLAMA_HOST=0.0.0.0`) and the container addresses it as `host.docker.internal`. That setup has
not been tested.

## Tests

```bash
cd services/api/frontend
npm run typecheck
npm test
```

There is no Python test suite. Both services validate the collection, the embedding model and
every payload at runtime, and refuse to run against a mismatch.

### Checks that pairs of files agree

Some files must agree but cannot share code: a subtree split ships only `services/<name>/`, the
frontend is TypeScript, Space frontmatter is read before any code runs, and pre-commit builds its
hook environments from a git ref rather than from `uv.lock`.
[`scripts/check_duplication.py`](../scripts/check_duplication.py) checks six of them:

```bash
uv run python scripts/check_duplication.py
```

| Pair | How it is checked |
|---|---|
| The two `app/contract.py` loaders | Shared definitions compared as syntax trees with string literals blanked, so messages may differ but logic may not |
| Both writers' payload keys and `conf/collection.yaml` | Keys read from the payload dicts and compared with the contract |
| Each Space README's `models:` and `preload_from_hub:` | Must list the contracted embedding model |
| The stream event types | The pydantic `Literal` compared with the frontend's `StreamEvent` union |
| The ruff version | `.pre-commit-config.yaml`'s `rev` compared with the `ruff==` pin in the `dev` group |
| The `rag.*` config keys | Every key `app/rag.py` reads must exist in `conf/config.yaml` |

## Linting and formatting

One ruff configuration in `pyproject.toml` covers both services. `pre-commit` and `ruff` are
installed by `uv sync`.

```bash
uv run pre-commit install              # run the hooks on every commit
uv run pre-commit run --all-files      # or run them now
```

The hooks run ruff lint and format, whitespace and end-of-file fixers, YAML and TOML checks, and
a check that relative links in Markdown files resolve. CI runs the same hooks. The `dev` group pins
the same ruff version as `.pre-commit-config.yaml`, so `uv run ruff check .` gives the same result
as CI.
