"""What /rewriteQuery returns: a short conversation title.

A distinct model from the request despite the identical field name -- this one
carries the shortened text, not the user's original question.
"""

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
