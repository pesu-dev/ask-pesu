"""Model representing a request made to the /ask route."""

from pydantic import BaseModel, ConfigDict, Field


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
        description="User's input query for the chatbot.",
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
