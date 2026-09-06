"""Model representing the response for the /health route."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HealthResponseModel(BaseModel):
    """Model representing the health check response."""

    model_config = ConfigDict(strict=True)

    status: bool = Field(
        ...,
        title="Service Status",
        description="Indicates whether the service is up.",
        json_schema_extra={"example": True},
    )

    message: str = Field(
        ...,
        title="Health Message",
        description="A human-readable message about the service status.",
        json_schema_extra={"example": "ok"},
    )

    timestamp: datetime = Field(
        ...,
        title="Response Timestamp",
        description="Timestamp of the health check with timezone info.",
        json_schema_extra={"example": "2025-09-14T12:34:56+05:30"},
    )
