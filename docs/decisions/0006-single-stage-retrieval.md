# 0006. Retrieval is single-stage

- **Status:** Accepted
- **Discussed in:** [#107](https://github.com/pesu-dev/ask-pesu/issues/107)

## Context

For some questions, the answering thread never reaches the model. Multi-stage designs were
proposed: find likely posts first using titles and bodies, then choose comment trees within those
posts.

## Decision

Keep single-stage retrieval: each phrasing searches the one collection, and the results are pooled
and reranked.

Multi-stage designs were measured in #107, using separate collections for each field combination.
The best reached the answering thread for about as many questions as the current pipeline, within
the noise of the labelled set, and each would need extra production collections kept in step with
the writer.

## Consequences

- One collection per environment, and one write per thread.
- The questions the pipeline misses are misses at retrieval. #107 lists them.

## Alternatives rejected

- **Two-stage retrieval** (posts, then comment trees), with several choices of index for each
  stage. No combination improved on single-stage by more than noise, and each costs extra
  collections.
