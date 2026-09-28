# 0003. Documents are chosen by relevance and ordered by upvotes

- **Status:** Accepted
- **Discussed in:** [#83](https://github.com/pesu-dev/ask-pesu/issues/83), [#87](https://github.com/pesu-dev/ask-pesu/pull/87), [#105](https://github.com/pesu-dev/ask-pesu/issues/105), [#110](https://github.com/pesu-dev/ask-pesu/pull/110)

## Context

After the cross-encoder cutoff, the pipeline has to decide which documents the model reads and in
what order. Two signals are available: the cross-encoder's relevance score, and the community's
response to the answer, `root_comment_score`. The post's own `score` is the same for every
document from a post and cannot go negative, so it cannot rank one reply against another.

## Decision

1. The `rerank.top_n` documents with the highest cross-encoder scores are chosen.
2. `rank()` orders them by `root_comment_score`, highest first, with a stable sort on the raw
   count.

Ties are common, because most answers have few upvotes, and the stable sort keeps tied documents
in relevance order.

## Consequences

- Upvotes decide the order the model reads documents in, and the order of the `sources` event. They
  do not decide which documents are sent.
- There are no ranking weights or normalising constants to configure. Sorting is unchanged by any
  monotonic transform of the score, so a normalised score would give the same order.
- A missing score counts as zero.

## Alternatives rejected

- **Relevance multiplied by a normalised upvote factor.** It needed a normalising constant taken
  from the corpus ([0002](0002-no-corpus-derived-configuration.md)). Removed in #87.
- **Sorting every document above the cutoff by upvotes, then keeping the top `top_n`.** The cutoff
  is permissive, so this let highly upvoted but weakly relevant documents displace relevant ones.
  Replaced by choosing on relevance first, in #110.
