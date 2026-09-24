<!--
Target `dev`, from a branch of your fork that is not `main`. `source.yaml` fails the PR otherwise.

Delete this comment.
-->

## 📌 Description

What this changes, and why.

> ℹ️ **Fixes / Related Issues**
> Fixes: #
> Related: #

## 🧱 Type of Change

- [ ] 🐛 Bug fix
- [ ] ✨ New feature
- [ ] ⚠️ Breaking change — to the `/ask` stream, a request or response schema, or `conf/collection.yaml`
- [ ] 🎯 Retrieval or answer quality — prompts, ranking, reranking, `rag.*` config
- [ ] 📝 Documentation
- [ ] ⚙️ CI/CD or deployment
- [ ] 🧹 Refactor, no behaviour change
- [ ] 🧰 Dependency update

## 🧪 How Has This Been Tested?

There is no Python test suite; both services validate the collection, the embedding model and every payload at startup instead. Tick what applies.

- [ ] `uv run pre-commit run --all-files`
- [ ] `uv run python scripts/check_duplication.py`
- [ ] `npm run typecheck` and `npm test`, in `services/api/frontend/` — for frontend changes
- [ ] Ran the service locally against `ask-pesu-prod`
- [ ] Checked the UI with `ENV=test`, which needs no Qdrant, token or quota
- [ ] Built and booted the image, vendoring the shared files first as in the README's [Docker](https://github.com/pesu-dev/ask-pesu/blob/dev/README.md#docker) section
- [ ] For retrieval or prompt changes: compared answers before and after on real questions

## ✅ Checklist

- [ ] Follows [CONTRIBUTING.md](https://github.com/pesu-dev/ask-pesu/blob/dev/.github/CONTRIBUTING.md)
- [ ] Self-reviewed the diff
- [ ] Comments describe what the code does, not why it is right — see [CONTRIBUTING.md](https://github.com/pesu-dev/ask-pesu/blob/dev/.github/CONTRIBUTING.md#comments-and-documentation)
- [ ] Updated the README where behaviour or configuration changed
- [ ] Recompiled `requirements.txt` if `pyproject.toml` changed, with the command in its header
- [ ] Changed both sides of any pair `check_duplication.py` guards — contract loaders, payload keys, stream event names, `rag.*` config keys
- [ ] No second committed copy of a shared root file (`conf/collection.yaml`, `requirements.txt`, `LICENSE`, `.env.example`)

## 🛠️ Affected Areas

### 🔍 AskPESU — `services/api`

- [ ] `app/rag.py` — retrieval, reranking, ranking or answer generation
- [ ] `conf/config.yaml` — prompts, models, retrieval knobs, limits
- [ ] `app/app.py` — routes, quota, error handling
- [ ] `app/models/` — request or response schemas
- [ ] `frontend/` — the UI

### ✍️ AskPESU DB — `services/db`

- [ ] `app/app.py` — the live listener
- [ ] `scripts/` — processing and backfill

### 🧩 Shared

- [ ] `conf/collection.yaml` — the collection contract; affects both services
- [ ] `pyproject.toml` / `requirements.txt` / `uv.lock`
- [ ] Dockerfiles
- [ ] `.github/workflows/` or `.github/actions/`

## 📸 Evidence (if applicable)

For a behaviour change: a before-and-after answer, a `curl` of the stream, or a screenshot of the UI. Required for breaking changes.

## 🧠 Additional Notes (if applicable)

Limitations, follow-up work, or anything the reviewer should look at first.
