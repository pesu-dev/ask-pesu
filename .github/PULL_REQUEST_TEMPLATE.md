

## 📌 Description

Please provide a concise summary of the changes:

- What is the purpose of this PR?
- What problem does it solve, or what feature does it add?
- Any relevant motivation, background, or context?

> ℹ️ **Fixes / Related Issues**
> Fixes: #100
> Related: #001

## 🧱 Type of Change

> *Please indicate the type of changes introduced in your PR. Anything left unchecked will be assumed to be non-relevant*

- [ ] 🐛 Bug fix – Non-breaking fix for a functional/logic error
- [ ] ✨ New feature – Adds functionality without breaking existing APIs
- [ ] ⚠️ Breaking change – Introduces backward-incompatible changes (API, schema, etc.)
- [ ] 📝 Documentation update – README, docstrings, OpenAPI tags, etc.
- [ ] ⚙️ CI/CD pipeline update – Modifies GitHub Actions, pre-commit, or Docker build
- [ ] 🧹 Code quality / Refactor – Improves structure, readability, or style (no functional changes)
- [ ] 🕵️ Debug/logging enhancement – Adds or improves logging/debug support
- [ ] 🔧 Developer tooling – Scripts,local testing improvements
- [ ] 🧰 Dependency update – Updates libraries in `requirements.txt`, `pyproject.toml`

## ✅ Checklist

> *Please indicate the work items you have carried out. Completing all the relevant items on this list is mandatory. Anything left unchecked will be assumed to be non-relevant*

- [ ] My code follows the [CONTRIBUTING.md](https://github.com/pesu-dev/ask-pesu/blob/dev/.github/CONTRIBUTING.md) guidelines
- [ ] I've performed a self-review of my changes
- [ ] I've added/updated necessary comments and docstrings
- [ ] I've updated relevant docs (README or endpoint docs)
- [ ] No new warnings introduced
- [ ] Docker image builds and runs correctly
- [ ] Changes are backwards compatible (if applicable)
- [ ] Feature flags or `.env` vars updated (if applicable)
- [ ] I've tested across multiple environments (if applicable)

## 🛠️ Affected API Behaviour

> *Please indicate the areas affected by changes introduced in your PR*

- [ ] `app/app.py` – Modified main FastAPI application logic or endpoints
- [ ] `app/rag.py` – Updated RAG pipeline or generation logic

### 🧩 Models
- [ ] `app/models/request.py` – Input validation or request schema changes
- [ ] `app/models/response.py` – Response formatting or schema changes

### 📚 Documentation & Endpoints
- [ ] `app/docs/ask.py` – API documentation for /ask endpoint
- [ ] `app/docs/health.py` – API documentation for /health endpoint
- [ ] `app/docs/base.py` – Base documentation structure

### 🐳 DevOps & Config
- [ ] `Dockerfile` – Changes to base image or build process
- [ ] `.github/workflows/*.yaml` – CI/CD pipeline or deployment updates
- [ ] `pyproject.toml` / `requirements.txt` – Dependency version changes
- [ ] `.pre-commit-config.yaml` – Linting or formatting hook changes
- [ ] `conf/config.yaml` – RAG configuration or system prompt changes

## ⚡ Performance Impact

> *Please indicate the performance implications of your changes*

- [ ] No significant performance degradation observed
- [ ] Memory usage impact assessed
