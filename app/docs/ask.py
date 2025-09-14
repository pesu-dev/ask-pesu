"""Custom docs for the /ask route."""

from app.docs.base import ApiDocs
from app.models import AskResponseModel

ask_docs = ApiDocs(
    request_examples={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "without_thinking": {
                            "summary": "Standard LLM request",
                            "value": {"query": "What is bootstrap at PES University?", "thinking": False},
                        },
                        "with_thinking": {
                            "summary": "LLM Request with 'thinking' mode",
                            "value": {"query": "What is bootstrap at PES University?", "thinking": True},
                        },
                    }
                }
            }
        }
    },
    response_examples={
        200: {
            "description": "Successful Question Answering",
            "model": AskResponseModel,
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
        429: {
            "description": "Quota Exceeded",
            "model": AskResponseModel,
            "content": {
                "application/json": {
                    "example": {
                        "status": False,
                        "message": "Thinking mode temporarily unavailable due to quota limits. Please try again later.",
                        "timestamp": "2024-07-28T22:35:10.103368+05:30",
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error",
            "model": AskResponseModel,
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
