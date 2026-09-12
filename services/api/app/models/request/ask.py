"""What clients send to /ask (and, reusing the same body, /rewriteQuery).

``strict=True`` makes pydantic refuse silent coercions -- a string "true" is
rejected rather than becoming ``True`` -- so a malformed client fails visibly.
"""

from pydantic import BaseModel, ConfigDict, Field

# Longest question accepted. A long real question is a couple of hundred
# characters, so this is an order of magnitude of headroom over anything anyone
# types, and it stops /ask being handed a megabyte to embed and rerank.
#
# Here rather than in conf/config.yaml because pydantic reads it when the class
# is defined, which happens before any configuration is loaded -- and because it
# then appears in the OpenAPI schema, where a client can see the limit.
MAX_QUERY_CHARS = 2000


class HistoryItem(BaseModel):
    """Model representing an item in the chat history list."""

    query: str = Field(..., description="Past user query.")
    answer: str = Field(..., description="Chatbot's answer to a prior query by the user.")


class AskRequestModel(BaseModel):
    """Model representing a request made to the /ask route."""

    model_config = ConfigDict(strict=True)

    query: str = Field(
        ...,
        title="Query",
        max_length=MAX_QUERY_CHARS,
        description=(
            f"User's input query for the chatbot. At most {MAX_QUERY_CHARS} characters; longer is "
            f"refused with a 422 rather than truncated, because answering a different question than "
            f"the one asked is worse than saying no."
        ),
        json_schema_extra={"example": "What is bootstrap?"},
    )

    thinking: bool = Field(
        False,
        title="Thinking Mode",
        description="Flag to indicate if the model should 'think' before answering to produce more accurate responses.",
        json_schema_extra={"example": True},
    )

    history: list[HistoryItem] = Field(
        default_factory=list,
        description="List of all previous queries and answers from the client-side.",
        json_schema_extra={
            "example": [
                {"query": "abcd", "answer": "1234"},
                {"query": "hello", "answer": "world"},
            ]
        },
    )
