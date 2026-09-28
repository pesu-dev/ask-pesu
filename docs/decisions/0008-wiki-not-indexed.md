# 0008. The r/PESU wiki is not indexed

- **Status:** Accepted
- **Discussed in:** [#81](https://github.com/pesu-dev/ask-pesu/issues/81)

## Context

r/PESU has two things called "the FAQ". The FAQs post is a list of links to ordinary threads,
which are already indexed. The wiki's `faq/` pages are separate prose, partly copied from threads
and partly not.

## Decision

Neither writer reads the wiki.

## Consequences

Content that exists only in the wiki cannot be retrieved.

Indexing it would need:

- a point id scheme that cannot collide with ids derived from comments;
- a decision on the contracted `root_comment_*` payload keys, which a wiki page has no value for;
- a rendering of a page as a document;
- a way to refresh pages, because a wiki edit produces no comment for the listener to see.

## Alternatives rejected

- **Indexing the wiki as documents.** Not worth the work above at the time. Reopen #81 if that
  changes.
