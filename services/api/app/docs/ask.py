"""OpenAPI examples for the /ask route.

The 200 response is a newline-delimited JSON stream, not a JSON document, so the
example below is a literal transcript of the wire format rather than an object.

FastAPI cannot infer a schema for that body, so the shape of ONE LINE is
attached explicitly, generated from :class:`AskStreamEventModel`. Without this
the models describing the stream are referenced by nothing and never reach the
published schema at all -- documented only in the source of the module that
defines them, which is the one place a client integrator does not look.
"""

from app.docs.base import ApiDocs
from app.models import AskErrorResponseModel, AskStreamEventModel

# Self-contained: `$defs` carries AskSourceModel along, so this can be inlined
# as the media type's schema without registering a component. OpenAPI 3.1 is
# JSON Schema, so the internal refs resolve where they sit.
STREAM_LINE_SCHEMA = AskStreamEventModel.model_json_schema()

ask_docs = ApiDocs(
    request_examples={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "without_thinking": {
                            "summary": "Standard LLM request",
                            "value": {"query": "What is bootstrap at PES University?", "thinking": False},
                        },
                        "with_thinking": {
                            "summary": "LLM Request with 'thinking' mode",
                            "value": {"query": "What is bootstrap at PES University?", "thinking": True},
                        },
                    }
                }
            }
        }
    },
    response_examples={
        200: {
            "description": (
                "Newline-delimited JSON, one object per line, streamed as generation proceeds; the "
                "schema below describes a single line. `sources` carries the threads retrieval "
                "selected and is sent once, before the first token, so a client can render citations "
                "while the answer is still being written -- it is sent even when empty. `step` events "
                "appear only in thinking mode. `done` is always last, including after `error`."
            ),
            "content": {
                "text/plain": {
                    "schema": STREAM_LINE_SCHEMA,
                    "example": (
                        '{"type": "sources", "sources": [{"permalink": '
                        '"https://reddit.com/r/PESU/comments/1kq6d08/", "title": "Bootstrap 2024 megathread", '
                        '"snippet": "bootstrap is a week of intro sessions before classes start...", '
                        '"created_utc": 1715000000.0}]}\n'
                        '{"type": "token", "content": "Bootstrap at PES University is "}\n'
                        '{"type": "token", "content": "a week-long series of activities for freshers."}\n'
                        '{"type": "done"}\n'
                    ),
                }
            },
        },
        429: {
            "description": "The requested model is in quota cooldown. Nothing is streamed.",
            "model": AskErrorResponseModel,
            "content": {
                "application/json": {
                    "example": {
                        "status": False,
                        "message": "Thinking mode is temporarily unavailable due to quota limits.",
                        "quota": {
                            "thinking": {"available": False, "next_available": "2025-09-15T00:42:19+05:30"},
                            "primary": {"available": True},
                        },
                        "timestamp": "2024-07-28T22:35:10.103368+05:30",
                    }
                }
            },
        },
        500: {
            "description": (
                "The request failed before streaming began. A failure *during* generation cannot use this "
                "shape -- the status line is already sent -- and arrives as an `error` event instead."
            ),
            "model": AskErrorResponseModel,
            "content": {
                "application/json": {
                    "example": {
                        "status": False,
                        "message": "An unexpected error occurred.",
                        "timestamp": "2024-07-28T22:40:10.103368+05:30",
                    }
                }
            },
        },
    },
)
