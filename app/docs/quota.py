"""Custom docs for the /quota route."""

from app.docs.base import ApiDocs
from app.models import QuotaResponseModel

quota_docs = ApiDocs(
    request_examples={},
    response_examples={
        200: {
            "description": "Quota Status",
            "model": QuotaResponseModel,
            "content": {
                "application/json": {
                    "example": {
                        "status": True,
                        "thinking": {"available": False, "next_available": "2025-09-14T12:00:00+05:30"},
                        "primary": {"available": True},
                        "timestamp": "2025-09-14T00:42:19+05:30",
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error",
            "model": QuotaResponseModel,
            "content": {
                "application/json": {
                    "example": {
                        "status": False,
                        "message": "Internal Server Error. Please try again later.",
                        "timestamp": "2024-07-28T22:30:10.103368+05:30",
                    }
                }
            },
        },
    },
)
