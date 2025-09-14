"""Model representing a request made to the /ask route."""

from pydantic import BaseModel, ConfigDict, Field


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
