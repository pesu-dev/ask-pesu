"""Model representing a request."""

from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    """Model representing a request."""

    model_config = ConfigDict(strict=True)

    query: str = Field(
        ...,
        title="Query",
        description="User's input query for the chatbot.",
        json_schema_extra={"example": "What is bootstrap?"},
    )
