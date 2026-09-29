# HTTP API

## `services/api`

The Swagger UI at `/docs` is generated from the pydantic models in `services/api/app/models/` and
the examples in `services/api/app/docs/`.

| Route | Body | Returns |
|---|---|---|
| `GET /`, `HEAD /` | — | The compiled frontend, sent with `Cache-Control: no-cache`. **503** with a JSON message if the frontend was never built |
| `POST /ask` | `{query, thinking?, history?}` | An NDJSON stream; see [The streaming protocol](#the-streaming-protocol). **429** if the requested model is in cooldown. **422** if the body is invalid, including a `query` longer than 2,000 characters |
| `POST /rewriteQuery` | The same body as `/ask`; only `query` is read | `{query}`: the question shortened to at most eight words, for the conversation sidebar |
| `GET /health` | — | `{status, message, timestamp}` |
| `GET /quota` | — | `{status, quota, timestamp}`, with one entry per model |
| `GET /docs` | — | Swagger UI |
| `GET /assets/*` | — | The frontend's hashed build files, cached for a year |

Files from `frontend/public/`, such as the favicon and `robots.txt`, are served at the root with
one route each. Timestamps in responses are in Indian Standard Time.

### `POST /ask`

```json
{
  "query": "Is CSE at RR harder than at EC?",
  "thinking": false,
  "history": [
    {"query": "What branches does PES offer?", "answer": "..."}
  ]
}
```

- **`query`**: the question, at most 2,000 characters.
- **`thinking`**: `true` answers with the thinking model and streams its reasoning as `step`
  events. Stages that run before the answer always use the primary model.
- **`history`**: previous `{query, answer}` turns, oldest first. The server stores no
  conversations, so the client sends the turns it wants considered.
  [pipeline.md](pipeline.md#conversation-history) describes how they are used.

The body is validated in strict mode, so types are not coerced: the string `"true"` is rejected
for `thinking`.

A request for a model in cooldown is refused with a 429 before streaming starts:

```json
{
  "status": false,
  "message": "Thinking mode is temporarily unavailable due to quota limits. ...",
  "quota": {
    "thinking": {"available": false, "next_available": "2026-09-08T12:00:00+05:30"},
    "primary": {"available": true}
  },
  "timestamp": "2026-09-07T12:00:00+05:30"
}
```

### `POST /rewriteQuery`

Returns `{"query": "..."}`. Instead of calling the model, it returns the first eight words of the
question when:

- the server runs with `ENV=test`;
- the primary model is in cooldown;
- the provider refuses the call for quota. The refusal also starts the primary model's cooldown.

Any other failure returns a 500.

### `GET /health`

Returns 200 with `{"status": true, "message": "ok", "timestamp": ...}` while the process is up. It
does not check Qdrant or the model provider. The server does not start unless the collection
passes its startup checks.

### `GET /quota`

```json
{
  "status": true,
  "quota": {
    "thinking": {"available": false, "next_available": "2026-09-08T12:00:00+05:30"},
    "primary": {"available": true}
  },
  "timestamp": "2026-09-07T12:00:00+05:30"
}
```

`next_available` is present only while a model is in cooldown. See
[failure-handling.md](failure-handling.md#quota-and-cooldowns).

### Errors

An unhandled exception returns a 500 with a generic message. The exception is logged, not
returned. Failures after `/ask` has started streaming arrive as `error` events instead.

## The streaming protocol

`/ask` returns one JSON object per line, with the content type `text/plain`. Each line is one
event:

| `type` | Fields | Meaning |
|---|---|---|
| `sources` | `sources` | The posts the answer draws on. Sent once, before the first `token`. May be empty |
| `step` | `content` | Reasoning text. Thinking mode only |
| `token` | `content` | A piece of the answer |
| `error` | `content` | Generation failed; `content` is the message |
| `done` | — | The end of the stream. Always the last event, whether the request succeeded or failed |

A normal answer streams `sources`, then `token` events, then `done`. In thinking mode, `step`
events come between `sources` and the first `token`. A failure sends `error` and then `done`; it
can happen before `sources` is sent.

Each entry in `sources` describes one post:

```json
{
  "permalink": "https://reddit.com/r/PESU/comments/1kq6d08/",
  "title": "Can someone explain the placement policy of PESU?",
  "snippet": "The Placement Policy if any of you are confused: 1) If you get a T1...",
  "created_utc": 1715000000.0
}
```

- **`permalink`**: the Reddit discussion. For a link post this is the discussion, not the linked
  article.
- **`title`**: the post's title, or the permalink if the document has no title line.
- **`snippet`**: the start of the comment tree, `sources.snippet_chars` characters long.
- **`created_utc`**: when the post was made, as a Unix timestamp, or `null`. This is the post's
  time, not the reply's.

Several documents from one post produce one entry, in the position of the highest-ranked one.

The model is told not to list sources in its answer. The `sources` event is the list of
citations.

### Changing an event

The event types are defined in three places:

- `services/api/app/models/response/ask.py`: the `Literal` in `AskStreamEventModel`.
- `services/api/app/rag.py`: where the events are emitted.
- `services/api/frontend/src/lib/api.ts`: the `StreamEvent` union the client parses.

[`scripts/check_duplication.py`](../scripts/check_duplication.py) fails if the `Literal` and the
`StreamEvent` union differ. Update `test_stream()` in `services/api/app/app.py` as well, so
`ENV=test` emits the new event.

## `services/db`

| Route | Returns |
|---|---|
| `GET /` | An HTML status page: whether the listener is running, which collection it writes, and why it stopped if it has. Always **200** |
| `GET /health` | `{"status": "ok"}`, or **503** with `{"status": "error", "detail": ...}` |

`/health` returns 503 when:

- the listener stopped on a contract violation, or
- the last `MAX_CONSECUTIVE_WRITE_FAILURES` (5) writes all failed. The listener keeps retrying in
  this case, and `/health` returns 200 again after a write succeeds.

`/` always returns 200 because the platform checks it to decide whether the Space is up. A 503
there could get the Space restarted repeatedly, and each restart loses the comments posted while
the listener is down. `/health` reports the failure instead.
