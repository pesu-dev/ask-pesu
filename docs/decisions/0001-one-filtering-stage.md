# 0001. The cross-encoder cutoff is the only relevance filter

- **Status:** Accepted
- **Discussed in:** [#83](https://github.com/pesu-dev/ask-pesu/issues/83), [#105](https://github.com/pesu-dev/ask-pesu/issues/105), [#108](https://github.com/pesu-dev/ask-pesu/issues/108), [#110](https://github.com/pesu-dev/ask-pesu/pull/110)

## Context

Several stages of the pipeline could drop documents: a similarity threshold at retrieval, the
cross-encoder, and the limit on how many documents reach the model. When more than one stage
filters, a document can be lost at a stage that is not judging relevance, and it is hard to tell
which stage lost it.

## Decision

`rerank.score_threshold`, applied to the cross-encoder's score, is the only place a document is
dropped for being a poor answer.

- `retrieval.k` and `retrieval.query_expansions` set how many candidates are retrieved.
- `rerank.top_n` sets how many of the documents above the cutoff the model reads, taken in
  cross-encoder order.
- `retrieval.score_threshold` is `null`. Under hybrid retrieval the fused score comes from rank
  positions and cannot be thresholded, and startup refuses a value.

## Consequences

- If nothing clears the cutoff, the model receives no context and says it does not have the
  information.
- Hybrid retrieval requires the reranker. Startup refuses `rerank.enabled: false` under `hybrid`.
- The cutoff is set low. The cross-encoder's scores for correct and incorrect documents overlap,
  so a higher cutoff drops correct documents as well as incorrect ones. Its job is to drop
  documents that are clearly off-topic.

## Alternatives rejected

- **A similarity threshold at retrieval.** It does not apply to hybrid scores, and under dense
  retrieval it would drop documents before the cross-encoder, which judges relevance better, has
  seen them.
- **Choosing the documents to send by upvotes.** This let upvotes override relevance; see
  [0003](0003-rank-by-upvotes.md).
