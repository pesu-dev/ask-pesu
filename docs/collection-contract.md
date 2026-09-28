# The collection contract

`services/db` writes the Qdrant collection and `services/api` reads it. They must agree on the
embedding model, the vector geometry, the vector names and the payload keys. A mismatch in the
embedding model or dimensions does not raise an error; it makes retrieval return the wrong
documents. So all of it is written once, in [`conf/collection.yaml`](../conf/collection.yaml), and
both services check it when they start.

**Change these values in `conf/collection.yaml`, never in a service.** Each service reads the
file through its own `app/contract.py`. Changes to `conf/collection.yaml` require review from the
codeowners.

## What is contracted

| | Value |
|---|---|
| Embedding model | `Alibaba-NLP/gte-modernbert-base` |
| Vector size / distance | 768 / Cosine |
| Dense vector name | `dense`. A named vector, so one collection holds both vectors |
| Sparse vector | `sparse`, with `modifier: idf`, from `Qdrant/bm25`. Written by the db and queried by the api under hybrid retrieval |
| Payload keys | `root_comment_id`, `root_comment_score`, `root_comment_author`, `post_id`, `author`, `url`, `permalink`, `score`, `upvote_ratio`, `created_utc`, `flair`, `nsfw` |

- **`permalink`** is what the api cites. For a link post, `url` is the external article, not the
  discussion. Both writers store `permalink` with the `https://reddit.com` prefix.
- **`root_comment_*`** describe the thread's root comment, the answer. The other keys describe the
  post, and are the same on every document from one post.
- **`sparse.model`** is contracted because the writer and the reader must tokenise text the same
  way. Qdrant applies the IDF weighting but does not tokenise.

Settings that do not affect stored vectors, such as prompts, model ids for generation, and
retrieval and reranking settings, are in `services/api/conf/config.yaml`. See
[configuration.md](configuration.md).

## Collections and keys

The collection name is not part of the contract. Each service reads it from `QDRANT_COLLECTION`,
which has no default. The cluster holds two collections:

| Collection | Used by | Key |
|---|---|---|
| `ask-pesu-prod` | The three Spaces. Local development that only reads | The db Space has a read-write key. Both api Spaces, and contributors, have read-only keys |
| `ask-pesu-dev` | CI. Local development that writes, such as running the listener or a backfill | A read-write key, which the codeowners give out on request |

Only the deployed db Space writes to `ask-pesu-prod`. Keys are scoped to one collection; a key
used against another collection gets a 403.

Every service must be given the collection it is meant to use. Each checks the shape of the
collection it is pointed at, but cannot tell that another service was pointed somewhere else. An
api reading a different collection from the one the db writes starts normally and never sees new
threads.

## How it is enforced

- **The writer** (`services/db`) creates the collection from the contract if it does not exist.
  If it does exist, the writer refuses to start unless its geometry matches. Every payload is
  checked before it is written; a payload whose keys differ from the contract stops the listener,
  and `/health` returns 503.
- **The reader** (`services/api`) refuses to start unless the collection matches, the loaded
  embedding model is the contracted one with the contracted width, and every payload key it reads
  is in the contract. The width is checked by embedding a probe string.
- **CI** checks that each shared file is tracked once, that `requirements.txt` matches
  `pyproject.toml`, that the tree each Space receives contains everything it needs, and that the
  two `contract.py` loaders and both writers' payload keys agree with the contract. See
  [ci-cd.md](ci-cd.md#continuous-integration).

To opt out of the sparse vector, remove the `sparse:` block. Both services then skip the sparse
checks and the writer writes dense vectors only. Hybrid retrieval needs the sparse vector, so the
api must also be set to `retrieval.mode: dense`.

## Creating a collection

`services/db` creates the collection from the contract on its first start. To create one by hand
in Qdrant Cloud instead:

| Field | Value |
|---|---|
| Collection name | `ask-pesu-prod` for deployments; `ask-pesu-dev` for CI and local writes |
| Dense vector name | `dense` |
| Dimension | `768` |
| Metric | `Cosine` |
| Sparse vector name | `sparse` |
| IDF modifier | **enabled** |

Without the IDF modifier, Qdrant scores raw term frequency, so a thread that repeats a common word
outranks one that answers the question, and nothing reports an error. Both services check for the
modifier at startup and refuse to run without it.

A new collection must exist before an api is pointed at it, because the api refuses to start
without one. Run `services/db` against it once, or create it by hand as above. See
[ci-cd.md](ci-cd.md#adding-an-environment).

### Payload indexes

The collections have no payload indexes, and retrieval does not filter on payload. The cluster
refuses a filter on a field that has no index, so adding a filter means adding its index first.
Indexes can be added to a populated collection at any time.

## Shared files and vendoring

These files are authored once, at the repository root, and CI fails if a second copy is tracked:
`conf/collection.yaml`, `requirements.txt`, `pyproject.toml`, `uv.lock`, `LICENSE` and
`.env.example`.

A deploy sends only `services/<name>/` to the Space (see
[architecture.md](architecture.md#each-service-is-shaped-like-a-repository-root)), so the deploy
first copies four of them into the service directory:

| File | Needed because |
|---|---|
| `conf/collection.yaml` | Both services refuse to start without it |
| `requirements.txt` | Both Dockerfiles install from it |
| `LICENSE` | The Space's README frontmatter declares the licence |
| `.env.example` | Documents the environment for anyone running the Space's code |

The deploy refuses to push a tree missing any of the four. `pyproject.toml` and `uv.lock` are not
copied, because neither Dockerfile reads them.

The copies are gitignored and never committed.

- **Running a service from a checkout** needs no copy. The loader walks up from `app/contract.py`
  and finds the root `conf/collection.yaml`. If both a copy and the root file exist and differ,
  the loader raises an error.
- **A Docker build** needs the copies, because the build context is the service directory:

  ```bash
  mkdir -p services/api/conf
  cp conf/collection.yaml services/api/conf/
  cp requirements.txt services/api/
  docker build services/api --tag ask-pesu
  ```
