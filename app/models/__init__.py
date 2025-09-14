"""Custom models for the AskPESU API."""

from .request.ask import AskRequestModel
from .response.ask import AskResponseModel
from .response.health import HealthResponseModel
from .response.quota import QuotaResponseModel

__all__ = [
    "AskRequestModel",
    "AskResponseModel",
    "HealthResponseModel",
    "QuotaResponseModel"
]
