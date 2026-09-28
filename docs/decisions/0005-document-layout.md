# 0005. A document embeds the post title, the post body and the comment tree

- **Status:** Accepted
- **Discussed in:** [#80](https://github.com/pesu-dev/ask-pesu/issues/80), [#107](https://github.com/pesu-dev/ask-pesu/issues/107)

## Context

Every document from one post starts with the same title and body, so documents from one post
embed similarly and can fill several of the top search results. #80 proposed embedding only the
title and the comment tree to reduce this.

## Decision

Keep the layout: `TITLE:`, `CONTENT:` (the post body), then `COMMENT TREE:`. The whole text is
embedded, both dense and sparse.

All seven combinations of the three fields were built as separate collections and measured through
the full pipeline. The current layout reached the answering thread for the most questions.
Removing the body made results worse. The measurements are in #80 and #107.

## Consequences

- Each field contributes differently: the title and body place the thread in its topic, and the
  comment tree carries most of the distinctive vocabulary.
- The cross-encoder scores each document without its body (`_without_body()`), so the replies fit
  in its input window. The answer prompt still receives the whole document.
- `format_docs()` writes each post's title and body once in the model's context, however many of
  its documents are sent.
- The layout is written by `services/db/app/app.py` and `services/db/scripts/populate_db.py`, and
  parsed by `describe_sources()`, `_without_body()` and `format_docs()` in
  `services/api/app/rag.py`. A change to the markers must change all of them.

## Alternatives rejected

- **Title and comment tree only** (#80's proposal), **body and comment tree**, **comment tree
  only**, and the layouts without the tree. Each reached the answering thread for fewer
  questions.
