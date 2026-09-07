"""OpenAPI examples for the /ask route.

The 200 response is a newline-delimited JSON stream, not a JSON document, so the
example below is a literal transcript of the wire format rather than an object.
"""

from app.docs.base import ApiDocs
from app.models import AskErrorResponseModel

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
                "Newline-delimited JSON. One object per line, streamed as generation proceeds. "
                "`step` events appear only in thinking mode. `done` is always last, including after `error`."
            ),
            "content": {
                "text/plain": {
                    "schema": {"type": "string", "format": "ndjson"},
                    "example": (
                        '{"type": "step", "content": "Searching documents..."}\n'
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
