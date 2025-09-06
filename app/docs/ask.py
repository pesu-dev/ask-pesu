"""Custom docs for the /ask endpoint."""

from app.docs.base import ApiDocs
from app.models import ResponseModel

ask_docs = ApiDocs(
    request_examples={
        "requestBody": {
            "content": {
                "application/json": {
                    "example": {
                        "query": "What is bootstrap at PES University?",
                    }
                }
            }
        }
    },
    response_examples={
        200: {
            "description": "Successful Question Answering",
            "model": ResponseModel,
            "content": {
                "application/json": {
                    "example": {
                        "status": True,
                        "message": "Answer generated successfully.",
                        "answer": (
                            "Bootstrap at PES University is a week-long (typically 5-day) series of activities "
                            "for freshers, usually held before regular classes commence. Its main purpose is to "
                            "help students socialize, make new friends, and network with batchmates and seniors. "
                            "It also allows them to explore various academic branches through simple and engaging "
                            "activities."
                        ),
                        "timestamp": "2024-07-28T22:30:10.103368+05:30",
                        "latency": 1.234,
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error",
            "model": ResponseModel,
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
