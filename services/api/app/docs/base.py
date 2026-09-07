"""The container every route's OpenAPI examples are packed into.

FastAPI takes request examples through ``openapi_extra`` and response examples
through ``responses``; pairing them in one frozen object keeps a route's
documentation in a single import.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ApiDocs:
    """Represents the base API documentation class holding example requests and responses."""

    request_examples: dict
    response_examples: dict
