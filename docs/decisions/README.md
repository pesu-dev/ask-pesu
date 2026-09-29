# Design decisions

Each record here states a decision that has been made, the reasons for it, and the alternatives
that were rejected. Read the relevant record before proposing to change one of these. A proposal
that reopens a decision should say what has changed since, and link the record.

The measurements behind a decision are in the linked issues and pull requests, not here.

| Record | Decision |
|---|---|
| [0001](0001-one-filtering-stage.md) | The cross-encoder cutoff is the only stage that drops a document for relevance |
| [0002](0002-no-corpus-derived-configuration.md) | No configuration value is derived from a snapshot of the corpus |
| [0003](0003-rank-by-upvotes.md) | The documents sent are chosen by relevance and ordered by the answer's upvotes |
| [0004](0004-no-global-recency-weight.md) | Retrieval and ranking have no recency weight |
| [0005](0005-document-layout.md) | A document embeds the post title, the post body and the comment tree |
| [0006](0006-single-stage-retrieval.md) | Retrieval is single-stage |
| [0007](0007-no-rate-limiting.md) | `/ask` has no per-client rate limit |
| [0008](0008-wiki-not-indexed.md) | The r/PESU wiki is not indexed |
| [0009](0009-conversations-in-the-browser.md) | Conversations are stored only in the browser |
| [0010](0010-db-deploys-only-to-production.md) | The db service is deployed only by the production deploy |

## Adding a record

Copy an existing record, give it the next number, and add it to the table. Keep the sections:
**Context**, **Decision**, **Consequences** and **Alternatives rejected**. Link the issue or pull
request where the decision was made. If a new decision replaces an old one, set the old record's
status to "Superseded by NNNN" rather than deleting it.
