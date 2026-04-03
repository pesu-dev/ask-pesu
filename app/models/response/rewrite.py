"""Model representing the response for the /rewrite route."""

from pydantic import BaseModel, ConfigDict, Field


class ShortenQueryModel(BaseModel):
    """Model to shorten the query."""

    model_config = ConfigDict(strict=True)
    query: str = Field(
        ...,
        title="Shortened Query",
        description="A Short summarised query for chat name",
        json_schema_extra={"example": "CGPA calculation at PESU"},
    )
