# 0002. No configuration value is derived from a snapshot of the corpus

- **Status:** Accepted
- **Discussed in:** [#77](https://github.com/pesu-dev/ask-pesu/issues/77), [#83](https://github.com/pesu-dev/ask-pesu/issues/83), [#87](https://github.com/pesu-dev/ask-pesu/pull/87)

## Context

The collection grows every day. A setting chosen to fit the corpus as it was on one day, such as a
score normaliser set from the upvote distribution or a list of topics that go out of date, becomes
wrong as the corpus changes, and nothing reports that it has.

## Decision

No configuration value may be derived from statistics of the corpus at a point in time. Where the
pipeline needs a behaviour that depends on the data, it uses a form that has no such constant.

## Consequences

- Ranking sorts on raw upvotes with no normalising constant; see [0003](0003-rank-by-upvotes.md).
- Deciding whether a question needs recent sources has to classify the question, not match it
  against a hand-written keyword list of volatile topics; see
  [0004](0004-no-global-recency-weight.md).
- Documentation and config comments describe what a setting does. Measurements go in issues and
  commits, where they are dated.

## Alternatives rejected

- **Tuned constants, re-tuned periodically.** Nothing detects when a re-tune is due, so the value
  is wrong in between.
