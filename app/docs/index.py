"""Custom docs for the / endpoint."""

from app.docs.base import ApiDocs

index_docs = ApiDocs(
    request_examples={},
    response_examples={
        200: {
            "description": "Serves the AskPESU frontend (index.html).",
            "content": {
                "text/html": {
                    "example": "<!DOCTYPE html><html><head><title>AskPESU</title></head><body>"
                    "<div id='root'></div></body></html>"
                }
            },
        },
        404: {
            "description": "index.html not found in the static distribution directory.",
            "content": {"application/json": {"example": {"detail": "Not Found"}}},
        },
    },
)
