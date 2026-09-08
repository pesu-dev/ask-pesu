# Contributing

Thanks for helping with ask-pesu. This file is the short path from a clone to a merged pull
request. It links into the [README](../README.md) rather than restating it, so the two cannot
drift — the README is always the reference.

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Setting up

```bash
git clone https://github.com/<your-fork>/ask-pesu.git
cd ask-pesu
uv sync --extra api --extra db
cp .env.example .env          # then fill it in
```

**`uv sync` is the only supported way to install dependencies.** It is the one command that gets
all of it right at once: both services' libraries, the linting tools, and torch from PyTorch's CPU
index rather than the CUDA build from PyPI. Do not install `requirements.txt` by hand — it is a
compiled artifact for the Space images, which have neither uv nor a lockfile. See
[Dependencies](../README.md#dependencies).

Run everything through `uv run`, which finds the environment from any directory in the repo:

```bash
uv run python -m app.app               # from services/api or services/db
uv run pre-commit run --all-files
```

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and, for frontend work,
Node.js 24. uv fetches Python itself.

Which environment variables are actually required, and where each value comes from, is in
[Environment variables](../README.md#environment-variables). Two that cost people time: write the
values **unquoted**, and set `ENV=test` if you are working on the frontend — it serves canned
responses, so you need no Qdrant, no `HF_TOKEN` and no inference quota.

## Opening a pull request

- **From a fork, on a branch that is not `main`, targeting `dev`.** `source.yaml` checks all
  three and fails the PR otherwise — including a PR opened from your fork's own `main`, so give
  the work its own branch. This repo's `main` is a deploy artifact, advanced only by the
  production workflow.
- **Run `uv run pre-commit run --all-files` first.** It is the same set of hooks CI runs.
- Reviewers are assigned by [CODEOWNERS](CODEOWNERS). Anything touching `conf/collection.yaml`
  affects both services and always needs owner review.

There is no Python test suite. The contract is enforced at runtime instead — both services
validate the live collection, the embedding model and every payload before doing any work — so
what CI checks is the structural invariants a running service cannot see. See
[Continuous integration](../README.md#continuous-integration).

## Four things that are easy to get wrong

1. **Shared files are authored once, at the repository root.** `conf/collection.yaml`,
   `requirements.txt`, `LICENSE` and `.env.example` are copied into each service at deploy time,
   because a `git subtree split` ships only `services/<name>/`. A second committed copy fails CI.
   See [Why builds copy shared files](../README.md#why-builds-copy-shared-files).
2. **Editing a dependency means recompiling `requirements.txt`**, with the exact command in
   `pyproject.toml` — `--group cpu` included, or torch resolves to the CUDA build and adds about
   4 GB to both images. CI recompiles and fails on any difference.
3. **Five pairs of files must agree and cannot import from each other**, so they are checked
   instead: `uv run python scripts/check_duplication.py`. If you change a contract loader, a
   payload key, a Space README's model list, a stream event name or the ruff version, change both
   sides.
4. **Anything that would make already-stored vectors unreadable belongs in
   `conf/collection.yaml`**, not in `services/api/conf/config.yaml`. Prompts, model ids and
   retrieval knobs are configuration; the embedding model and vector shape are a contract between
   the writer and the reader. See [The collection contract](../README.md#the-collection-contract).

## Reporting something instead

Bugs and ideas go to [Issues](https://github.com/pesu-dev/ask-pesu/issues). Anything with a
security impact should reach the maintainers privately rather than a public issue.
