# Contributing

This repository holds two services: **AskPESU** (`services/api`), which answers questions, and
**AskPESU DB** (`services/db`), which fills the search index it answers from.

This file is the short path from a clone to a merged pull request. It links into the
[README](../README.md) rather than restating it.

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Setting up

```bash
git clone https://github.com/<your-fork>/ask-pesu.git
cd ask-pesu
uv sync --extra api --extra db
cp .env.example .env          # then fill it in
```

**Install dependencies with `uv sync` only.** It installs both services' libraries, the linting
tools, and torch from PyTorch's CPU index rather than the CUDA build from PyPI. Do not install
`requirements.txt` by hand — it is a compiled artifact for the Space images, which have neither
uv nor a lockfile. See [Dependencies](../README.md#dependencies).

Run everything through `uv run`, which finds the environment from any directory in the repo:

```bash
uv run python -m app.app               # from services/api or services/db
uv run pre-commit run --all-files
```

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and, for frontend work,
Node.js 24. uv fetches Python itself.

The required environment variables, and where each value comes from, are in
[Environment variables](../README.md#environment-variables). Write the values **unquoted**. For
frontend work, set `ENV=test`: it serves canned responses and needs no Qdrant, no `HF_TOKEN` and
no inference quota.

## Opening a pull request

- **From a fork, on a branch that is not `main`, targeting `dev`.** `source.yaml` checks all
  three and fails the PR otherwise, including one opened from your fork's own `main`. This repo's
  `main` is advanced only by the production workflow.
- **Run `uv run pre-commit run --all-files` first.** It runs the same hooks CI does.
- **For frontend changes, run `npm run typecheck` and `npm test`** in `services/api/frontend/`.
  `vite build` strips types without checking them, so these are the only things that catch a type
  error before it reaches the browser.
- Reviewers are assigned by [CODEOWNERS](CODEOWNERS). Anything touching `conf/collection.yaml`
  affects both services and always needs owner review.

There is no Python test suite. Both services validate the live collection, the embedding model
and every payload before doing any work, so CI checks the structural invariants a running service
cannot see, and typechecks and tests the frontend. See
[Continuous integration](../README.md#continuous-integration).

## Shared files and contracts

1. **Shared files are authored once, at the repository root.** `conf/collection.yaml`,
   `requirements.txt`, `LICENSE` and `.env.example` are copied into each service at deploy time,
   because a `git subtree split` ships only `services/<name>/`. A second committed copy fails CI.
   See [Why builds copy shared files](../README.md#why-builds-copy-shared-files).
2. **Editing a dependency means recompiling `requirements.txt`**, with the exact command in
   `pyproject.toml`. Keep `--group cpu`: without it torch resolves to the CUDA build and both images
   grow by an order of magnitude. CI recompiles and fails on any difference.
3. **Six pairs of files must agree and cannot import from each other**, so they are checked
   instead: `uv run python scripts/check_duplication.py`. If you change a contract loader, a
   payload key, a Space README's model list, a stream event name, the ruff version or a `rag.*`
   config key, change both sides.
4. **Anything that would make already-stored vectors unreadable belongs in
   `conf/collection.yaml`**, not in `services/api/conf/config.yaml`. Prompts, model ids and
   retrieval knobs are configuration; the embedding model and vector shape are a contract between
   the writer and the reader. See [The collection contract](../README.md#the-collection-contract).

## Comments and documentation

State what the code does. Keep a comment only when it tells the reader something the code
does not: a constraint, a footgun, an ordering requirement, or why the obvious alternative is
wrong.

- **Do not defend a value.** If a number is a guess, say so — `NOT MEASURED. Five is a guess.` —
  and stop.
- **Do not narrate what changed.** Describe the code as it is. The history belongs in the commit
  message.
- **Do not put measurements in comments.** Timings, benchmarks and corpus statistics go in the
  commit or issue that produced them, because the code outlives the numbers.
- **If a sentence can be deleted without the reader losing a fact, delete it.**

## Reporting something instead

Bugs and ideas go to [Issues](https://github.com/pesu-dev/ask-pesu/issues). Security problems go to
the maintainers privately — see [SECURITY.md](SECURITY.md).
