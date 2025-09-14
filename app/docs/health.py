"""Custom docs for the /health route."""

from app.docs.base import ApiDocs
from app.models import HealthResponseModel

health_docs = ApiDocs(
    request_examples={},
    response_examples={
        200: {
            "description": "Successful Health Check.",
            "model": HealthResponseModel,
            "content": {
                "application/json": {
                    "example": {
                        "status": True,
                        "message": "ok",
                        "timestamp": "2024-07-28T22:30:10.103368+05:30",
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error.",
            "model": HealthResponseModel,
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
