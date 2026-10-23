"""Public typed client for the Search Service operation boundary."""

from src.search.client import (
    SearchClient,
    SearchClientError,
    SearchClientSettings,
    get_search_client,
)
from src.search.contracts import NewsSearchRequest, SearchResult, WebSearchRequest

__all__ = [
    "NewsSearchRequest",
    "SearchClient",
    "SearchClientError",
    "SearchClientSettings",
    "SearchResult",
    "WebSearchRequest",
    "get_search_client",
]
