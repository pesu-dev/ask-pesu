"""Models describing what ``POST /ask`` sends back.

``/ask`` does not return a JSON document. It streams newline-delimited JSON, one
object per line, so the client can render tokens as they arrive instead of
waiting for the whole answer. These models exist to describe that stream in the
OpenAPI schema; FastAPI cannot validate a streaming body against them.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AskStreamEventModel(BaseModel):
    """One line of the ``/ask`` NDJSON stream.

    The client reads until it sees ``done``, which is always sent last, on both
    the success and failure paths.
    """

    model_config = ConfigDict(strict=True)

    type: Literal["step", "token", "done", "error"] = Field(
        ...,
        title="Event Type",
        description=(
            "`step` is reasoning text, emitted only in thinking mode. `token` is a piece of the answer. "
            "`error` means generation failed and carries the reason. `done` terminates the stream and "
            "carries no content."
        ),
        json_schema_extra={"example": "token"},
    )

    content: str | None = Field(
        None,
        title="Event Content",
        description="Text carried by the event. Absent on `done`.",
        json_schema_extra={"example": "Bootstrap at PES University is a week-long series of activities"},
    )


class AskErrorResponseModel(BaseModel):
    """A non-streaming error body, returned when the request is refused before generation starts.

    Once the stream has begun the status code and headers are already sent, so
    later failures arrive as an ``error`` event instead of a body like this one.
    """

    model_config = ConfigDict(strict=True)

    status: bool = Field(
        ...,
        title="Request Status",
        description="Always false; successful requests stream instead.",
        json_schema_extra={"example": False},
    )

    message: str = Field(
        ...,
        title="Error Message",
        description="Human-readable reason the request was refused.",
        json_schema_extra={"example": "Primary LLM is temporarily unavailable due to quota limits."},
    )

    timestamp: datetime = Field(
        ...,
        title="Response Timestamp",
        description="When the error was produced, in IST.",
        json_schema_extra={"example": "2024-07-28T22:30:10.103368+05:30"},
    )

    quota: dict | None = Field(
        None,
        title="Quota Snapshot",
        description="Per-model cooldown state, included on 429 so the client can say when to retry.",
        json_schema_extra={"example": {"primary": {"available": False, "next_available": "2025-09-15T00:42:19+05:30"}}},
    )
