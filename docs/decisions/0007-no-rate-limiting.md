# 0007. `/ask` has no per-client rate limit

- **Status:** Accepted
- **Discussed in:** [#79](https://github.com/pesu-dev/ask-pesu/issues/79), [#94](https://github.com/pesu-dev/ask-pesu/pull/94)

## Context

`/ask` is public and unauthenticated, and each request costs embedding, reranking and LLM calls.
#79 proposed input limits, a request timeout, and per-IP rate limiting.

## Decision

`/ask` has no per-IP or per-client rate limit. The cost of each request is bounded instead:

- `query` is limited to 2,000 characters, and a longer one is refused with a 422;
- a request carries at most `limits.history_turns` turns of history, and older turns are dropped;
- `limits.timeout_seconds` bounds the whole request;
- the quota cooldowns refuse requests to a model the provider is already refusing, on `/ask` and
  `/rewriteQuery`.

## Consequences

These limits bound what one request costs and how long it holds a connection. They do not bound
how many requests arrive.

## Alternatives rejected

- **Per-IP rate limiting.** Not implemented, by decision in #79.
