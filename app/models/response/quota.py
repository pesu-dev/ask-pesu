"""Models representing the response for the /quota route."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class QuotaItemModel(BaseModel):
    """Represents the quota state of a single LLM."""

    model_config = ConfigDict(strict=True)

    available: bool = Field(
        ...,
        title="Availability",
        description="Whether this LLM is currently available for use.",
        json_schema_extra={"example": True},
    )

    next_available: datetime | None = Field(
        None,
        title="Next Availability",
        description="Timestamp when this LLM will next be available. Null if already available.",
        json_schema_extra={"example": "2025-09-15T00:42:19+05:30"},
    )


class QuotaResponseModel(BaseModel):
    """Response model for the /quota route."""

    model_config = ConfigDict(strict=True)

    status: bool = Field(
        ...,
        title="Request Status",
        description="Indicates whether the quota status was successfully retrieved.",
        json_schema_extra={"example": True},
    )

    thinking: QuotaItemModel = Field(
        ...,
        title="Thinking Mode Quota",
        description="Quota state for the Thinking LLM.",
    )

    primary: QuotaItemModel = Field(
        ...,
        title="Primary Mode Quota",
        description="Quota state for the Primary LLM.",
    )

    timestamp: datetime = Field(
        ...,
        title="Request Timestamp",
        description="Timestamp when the quota status was generated.",
        json_schema_extra={"example": "2025-09-14T00:42:19+05:30"},
    )
