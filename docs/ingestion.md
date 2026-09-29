# Ingestion

`services/db` writes the Qdrant collection that `services/api` answers from. The collection gets
data two ways:

- **The listener** (`services/db/app/app.py`) runs in the `askpesu-db` Space and indexes new
  comments as they are posted.
- **The backfill** (`services/db/scripts/`, or `notebooks/backfill.ipynb`) rebuilds history from
  a Reddit dump.

Both write the same kind of point, as described below.

## What a point is

The unit of indexing is a **thread**: one root comment and all of its replies. Each thread is one
point, and so one document (see [Terms](README.md#terms)).

A reply such as "yes, around 8.5" means nothing on its own, so the document also carries the post
it belongs to. Its text is:

```
TITLE: <post title>
CONTENT: <post body>
COMMENT TREE: <the thread, rendered as an indented tree>
```

`services/api` parses these three markers when it builds citations, reranks and formats the
prompt context. See [pipeline.md](pipeline.md).

- **The point id** is a UUIDv5 of the root comment's Reddit id (`convert_to_uuid` in
  `services/db/app/utils.py`). Writing the same thread again overwrites its point, so a busy
  thread never accumulates duplicates.
- **Every point has two vectors**: a dense embedding from the contracted embedding model, and a
  BM25 sparse vector from `fastembed`. `services/api` queries both.
- **The payload** keys are fixed by `conf/collection.yaml`. `root_comment_score` and
  `root_comment_author` belong to the thread's root comment, the answer. `score`, `author` and the
  other keys belong to the post, and are the same on every document from that post. Ranking uses
  `root_comment_score`. See [collection-contract.md](collection-contract.md).

## The listener

A daemon thread consumes `subreddit.stream.comments(skip_existing=True)`. For each new comment it:

1. skips the comment if AutoModerator wrote it;
2. walks up to the thread's root comment;
3. renders the whole thread with `build_thread_string` in `services/db/app/utils.py`, which
   refreshes the root comment so praw loads every reply;
4. validates the payload against the contract, embeds the document and upserts it.

`index_comment()` does all of this, and both the live stream and the startup catch-up call it.

### Catch-up on startup

The stream only yields comments posted after it opens, and the Space restarts on every production
deploy. Before opening the stream, the listener re-indexes the threads behind the most recent
`CATCH_UP_COMMENTS` comments (100), once per distinct thread. Writes are upserts keyed on the root
comment, so re-indexing a thread the stream has already written replaces it with the same content.

The catch-up runs once, at startup. When the stream fails on a network or Reddit error, the
listener re-enters the stream without catching up, so comments posted during that gap are missed
until the next backfill. A comment older than the catch-up window is only indexed by a backfill,
or when a newer comment in the same thread arrives.

### When the listener stops

- **A contract violation** (a payload whose keys differ from `conf/collection.yaml`) stops the
  listener. `/health` then returns 503 with the reason. Retrying cannot fix it.
- **Any other error** is logged and the stream is re-entered.
- **Consecutive failed writes**: after `MAX_CONSECUTIVE_WRITE_FAILURES` (5) writes in a row fail,
  `/health` returns 503 while the listener keeps retrying. A revoked key, a wrong URL or a deleted
  collection cause this.

See [api.md](api.md#servicesdb) for the routes, and
[development.md](development.md#db-listener) for running it locally.

## The backfill

The backfill runs in two stages. Run both from `services/db`.

### 1. Rebuild threads from a dump

The input is two JSONL exports of r/PESU, one of posts and one of comments. The script writes one
JSON file per post, holding one entry per root comment and its replies:

```bash
cd services/db
uv run python scripts/generate_processed_data.py \
    --posts ../../dump/r_PESU_posts.jsonl \
    --comments ../../dump/r_PESU_comments.jsonl \
    --output-dir processed_data
```

`--posts` and `--comments` default to `r_r_PESU_posts.jsonl` and `r_r_PESU_comments.jsonl` in the
working directory. `--workers` sets the number of worker processes (one per core by default).

Deleted and removed comments, and AutoModerator's standard reply, are dropped from the tree. The
tree is rendered with the same `render_tree` the listener uses. The listener does not apply the
same filtering, so a thread written by each path can differ; this is tracked in
[#123](https://github.com/pesu-dev/ask-pesu/issues/123).

### 2. Embed and upsert

`populate_db.py` writes the same point the listener writes: the same id, text layout, payload keys
and vectors, all read from the contract.

```bash
uv run python scripts/populate_db.py --data-dir processed_data --dry-run   # check first
uv run python scripts/populate_db.py --data-dir processed_data
```

| Option | Default | Meaning |
|---|---|---|
| `--data-dir` | `processed_data` | The per-post JSON files from stage 1 |
| `--completed-dir` | `completed` | Where each input file moves once all of its documents are stored |
| `--batch-size` | 128 | Documents per upsert, filled across files |
| `--encode-batch-size` | 8 | Documents the embedding model encodes at once |
| `--dry-run` | off | Validate the collection, parse every file and check every payload, without loading the embedding model or writing |

- **Resuming.** An input file moves to `--completed-dir` only after every document in it is
  stored, so an interrupted run resumes from the files left in `--data-dir`.
- **Verification.** After the run, every written id is read back. Any that are missing are listed
  in `missing_points.json`, next to the completed directory.
- **The dump replaces what is stored.** Every thread in the dump is re-embedded and overwrites the
  existing point. There is no option to keep the stored copy.
- **Run it with the listener stopped** where possible. Both write by the same id, so running both
  is safe, but embeds threads twice.
- **Collection.** The backfill writes the collection named by `QDRANT_COLLECTION`, and needs a
  read-write key to it. Contributors use `ask-pesu-dev`; see
  [collection-contract.md](collection-contract.md#collections-and-keys).

### Using a GPU

Embedding is most of the backfill's run time. The default `cpu` dependency group installs the CPU
build of torch, which the Spaces need, so a plain `uv sync` embeds on the CPU even on a machine
with a GPU. `populate_db.py` prints the device it uses and warns when it is the CPU.

To use CUDA, switch groups. `--no-group cpu` is required, because `cpu` is a default group and the
two are declared as conflicting:

```bash
uv sync --extra api --extra db --no-group cpu --group gpu
```

Pass the same flags to every `uv run` for the rest of the backfill:

```bash
uv run --no-group cpu --group gpu python scripts/populate_db.py --data-dir processed_data --dry-run
uv run --no-group cpu --group gpu python scripts/populate_db.py --data-dir processed_data
```

`uv run` syncs the environment before running, so a plain `uv run` reinstalls the CPU build over
the CUDA one. If the script reports `cpu` after a GPU sync, a plain `uv run` has switched it back.

Both groups resolve the same torch version, and `requirements.txt` is unaffected. To switch back,
run `uv sync --extra api --extra db`. The CUDA release is set by the `pytorch-cu126` index URL in
`pyproject.toml`.

### The notebook

`notebooks/backfill.ipynb` runs both stages and calls the same `backfill()` function as
`populate_db.py`. It runs on a local kernel, on a remote kernel attached from an editor (such as
VS Code on a Colab runtime), or uploaded on its own to Colab or Kaggle, where it clones the
repository. It needs the raw dump and a `.env`, and its first cells explain how to supply both to
a hosted kernel.
