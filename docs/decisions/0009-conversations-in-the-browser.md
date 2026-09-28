# 0009. Conversations are stored only in the browser

- **Status:** Accepted

## Context

A follow-up question needs the earlier turns of its conversation. They could be stored on the
server or kept by the client.

## Decision

The server stores no conversations. The frontend keeps them in `localStorage`
(`askpesu-conversations`) and sends the turns it wants considered as `history` with each request.

## Consequences

- The api holds no user data between requests, and needs no accounts or database of its own.
- Conversations do not move between browsers or devices, and clearing site data deletes them.
- The server bounds what a request may carry: `limits.history_turns` turns, of which the answer
  prompt receives `history.answer_turns`.
- The system prompt forbids answering from the history, because the history includes the model's
  own previous answers. Every fact has to come from the retrieved threads.

## Alternatives rejected

- **Server-side conversation storage.** It would need accounts or session identifiers, and a store
  for user data.
