"""Custom documentation module for askPESU API."""

from .ask import ask_docs
from .health import health_docs
from .index import index_docs
from .quota import quota_docs

__all__ = [
    "ask_docs",
    "health_docs",
    "index_docs",
    "quota_docs",
]
