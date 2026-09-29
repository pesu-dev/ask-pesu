# Configuration

Two places configure the services:

- **Environment variables**: credentials, the collection name, and local-only switches. Set in
  `.env` locally, and as Space secrets in production.
- **`services/api/conf/config.yaml`**: the models, prompts, and retrieval and reranking settings.
  Committed, and shared by every environment.

The embedding model, vector geometry and payload keys are in neither. They are in
`conf/collection.yaml`; see [collection-contract.md](collection-contract.md).

## Environment variables

Copy [`.env.example`](../.env.example) to `.env` at the repository root and fill it in. One `.env`
serves both services: `load_dotenv()` searches upward from the module that calls it. `.env` is
gitignored.

| Variable | Used by | Value |
|---|---|---|
| `QDRANT_URL` | api, db | Qdrant Cloud → your cluster → Overview → Endpoint |
| `QDRANT_API_KEY` | api, db | A key scoped to the collection below. A key scoped to another collection gets a 403 |
| `QDRANT_COLLECTION` | api, db | Required, with no default. `ask-pesu-prod` to read (read-only key); `ask-pesu-dev` to write (read-write key from the codeowners). See [collections and keys](collection-contract.md#collections-and-keys) |
| `HF_TOKEN` | api | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). A **Read** token is enough |
| `REDDIT_CLIENT_ID` | db | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → create a **script** app. The id is the string under the app's name |
| `REDDIT_CLIENT_SECRET` | db | The same app's **secret** field |
| `REDDIT_USERNAME` | db | The username of the account that owns the script app, without `/u/`; required in the Reddit API User-Agent |
| `ENV` | api | Optional. `test` serves canned answers without building the pipeline; see [development.md](development.md#working-without-credentials) |
| `LLM_MODE` | api | Optional. `hf` (the default) uses Hugging Face Inference; `ollama` uses a local ollama server; see [development.md](development.md#answering-from-a-local-ollama) |
| `OLLAMA_BASE_URL` | api | Required when `LLM_MODE=ollama`. The ollama server's URL |
| `OLLAMA_PRIMARY_MODEL` | api | Required when `LLM_MODE=ollama`. The ollama tag used in place of `llm.primary` |
| `OLLAMA_THINKING_MODEL` | api | Required when `LLM_MODE=ollama`. The ollama tag used in place of `llm.thinking` |
| `OLLAMA_NUM_CTX` | api | Optional. The context window the local models load with. Defaults to 16384 |
| `ASKPESU_CONFIG_PATH` | api | Set by `--config`; you do not normally set it. The path to `config.yaml` |

**Write values unquoted.** `python-dotenv` strips surrounding quotes, but `docker run --env-file`
passes them through as part of the value.

`HF_TOKEN` is required whenever the api builds its pipeline, including under `LLM_MODE=ollama`. It
authenticates Inference calls and model downloads. Without it the api fails with a `KeyError`
before it starts serving. It is not needed under `ENV=test`.

In production, each Space sets the same names under **Settings → Variables and secrets**. See
[ci-cd.md](ci-cd.md#space-configuration).

## `services/api/conf/config.yaml`

Changes take effect when the server restarts. `--config <path>` selects a different file; it is
passed to the server through `ASKPESU_CONFIG_PATH`, because uvicorn imports the app module afresh.

Every setting is under `rag`.

### Models: `llm.primary`, `llm.thinking`

`primary` writes the answer in normal mode, and makes every other LLM call in both modes: the
rewrite, the expansion and the conversation title. `thinking` only writes the answer in thinking
mode.

| Key | Default (primary / thinking) | Meaning |
|---|---|---|
| `repo_id` | `Qwen/Qwen3-4B-Instruct-2507` / `Qwen/Qwen3-4B-Thinking-2507` | The model on Hugging Face |
| `provider` | `nscale` | The Inference provider that serves the model |
| `temperature` | `0.3` | Sampling temperature |
| `max_new_tokens` | `2048` / `4096` | Token budget for one response. For the thinking model this covers reasoning and answer together |
| `timeout` | `120` / `240` | Seconds to wait on one provider call |

Under `LLM_MODE=ollama`, the `OLLAMA_*_MODEL` variables replace `repo_id` and `provider`. The other
keys still apply.

### Retrieval: `retrieval`

| Key | Default | Meaning |
|---|---|---|
| `mode` | `hybrid` | `hybrid` queries the dense and BM25 sparse vectors and fuses them; `dense` queries the dense vector only |
| `query_expansions` | `3` | Alternative phrasings written per question. The query itself is also searched, so `query_expansions + 1` searches run |
| `k` | `15` | Documents retrieved per search. With `query_expansions` it sets the size of the pool the cross-encoder scores before the first token |
| `score_threshold` | `null` | Cosine cutoff, `dense` mode only. Must be `null` under `hybrid` |

### Reranking: `rerank`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` skips the cross-encoder and does not load torch. Not allowed under `hybrid` |
| `model` | `cross-encoder/ms-marco-MiniLM-L6-v2` | The cross-encoder |
| `score_threshold` | `0.1` | The relevance cutoff, on the cross-encoder's 0–1 scale. Documents below it are dropped |
| `top_n` | `20` | The most relevant documents above the cutoff that are sent to the model. Costs prompt tokens |
| `concurrency` | `1` | Cross-encoder passes allowed at once, across all requests |

### Request limits and history: `limits`, `history`

| Key | Default | Meaning |
|---|---|---|
| `limits.history_turns` | `50` | Turns a request may carry. Older turns are dropped. Not measured |
| `limits.timeout_seconds` | `240` | Seconds for all of `/ask`: retrieval and every LLM call |
| `history.answer_turns` | `4` | Complete turns the answer prompt receives. The rewrite receives all of them. Not measured |

### Sources and prompts: `sources`, `prompts`

| Key | Default | Meaning |
|---|---|---|
| `sources.snippet_chars` | `200` | Length of the preview in each `sources` entry. Display only |
| `prompts.system_prompt` | — | The answer's system prompt |
| `prompts.answer_prompt` | — | The final user turn: `{question}` and `{context}` |
| `prompts.rewrite_prompt` | — | Rewrites a follow-up into a standalone question; takes `{chat_history}` |
| `prompts.multi_query_prompt` | — | Writes the alternative phrasings; takes `{count}` and `{question}` |

The placeholders are filled in by `app/rag.py`; renaming one breaks the prompt. The system prompt
describes the `(posted <Month Year>)` heading that `_heading()` in `app/rag.py` writes, so change
the two together.

[pipeline.md](pipeline.md) describes what each stage does with these settings.

### Checked at startup

The api refuses to start, naming the setting to change, when:

- `retrieval.mode` is neither `dense` nor `hybrid`;
- `retrieval.mode` is `hybrid` and `retrieval.score_threshold` is set, `rerank.enabled` is
  `false`, or `conf/collection.yaml` has no sparse vector;
- `history.answer_turns` is not a non-negative integer, `limits.history_turns` is not a positive
  integer, or `limits.timeout_seconds` is not a positive number;
- the file has a `search_kwargs`, `reranker` or `ranking` block. None of these is read; the error
  names the setting that replaces each.

`scripts/check_duplication.py` checks that every `rag.*` key `app/rag.py` reads exists in
`conf/config.yaml`.
