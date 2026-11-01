from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import ValidationError

from src.search.contracts import (
    NewsSearchRequest,
    SearchFailure,
    SearchOperationResult,
    SearchSuccess,
    WebSearchRequest,
)
from src.shared.internal_services import get_request_principal
from src.shared.kernel.correlation import resolve_correlation_id


@dataclass(frozen=True)
class SearchClientSettings:
    base_url: str
    service_token: str

    @classmethod
    def from_env(cls) -> SearchClientSettings:
        return cls(
            base_url=os.getenv("SEARCH_SERVICE_URL", "http://search-service:8003"),
            service_token=os.getenv("SEARCH_SERVICE_TOKEN", ""),
        )


class SearchClientError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class SearchClient:
    def __init__(
        self,
        settings: SearchClientSettings | None = None,
        *,
        client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or SearchClientSettings.from_env()
        headers = (
            {"Authorization": f"Bearer {self._settings.service_token}"}
            if self._settings.service_token
            else {}
        )
        self._headers = headers
        self._client = client or httpx.Client(headers=headers, timeout=None)
        self._async_client = async_client or httpx.AsyncClient(
            headers=headers, timeout=None
        )
        self._owns_client = client is None
        self._owns_async_client = async_client is None

    def search_web(self, request: WebSearchRequest) -> SearchOperationResult:
        return self._search("web", request)

    async def search_news(self, request: NewsSearchRequest) -> SearchOperationResult:
        correlation_id, payload = self._payload(request)
        try:
            response = await self._async_client.post(
                f"{self._settings.base_url.rstrip('/')}/v1/search/news",
                json=payload,
                headers=self._headers_for(correlation_id),
                timeout=request.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise SearchClientError(
                "DEADLINE_EXCEEDED", "search request timed out", retryable=False
            ) from exc
        except httpx.TransportError as exc:
            raise SearchClientError(
                "UPSTREAM_UNAVAILABLE", "search service is unavailable", retryable=True
            ) from exc
        return self._decode(response, correlation_id, "news")

    def _search(
        self, operation: str, request: WebSearchRequest | NewsSearchRequest
    ) -> SearchOperationResult:
        correlation_id, payload = self._payload(request)
        try:
            response = self._client.post(
                f"{self._settings.base_url.rstrip('/')}/v1/search/{operation}",
                json=payload,
                headers=self._headers_for(correlation_id),
                timeout=request.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise SearchClientError(
                "DEADLINE_EXCEEDED", "search request timed out", retryable=False
            ) from exc
        except httpx.TransportError as exc:
            raise SearchClientError(
                "UPSTREAM_UNAVAILABLE", "search service is unavailable", retryable=True
            ) from exc
        return self._decode(response, correlation_id, operation)

    def _payload(
        self, request: WebSearchRequest | NewsSearchRequest
    ) -> tuple[str, dict[str, object]]:
        principal = get_request_principal()
        if principal is None:
            raise SearchClientError(
                "AUTHENTICATION_FAILED",
                "authenticated search principal is required",
                retryable=False,
            )
        correlation_id = resolve_correlation_id()
        context = {
            "principal": principal.model_dump(mode="json"),
            "correlation_id": correlation_id,
            "contract_version": "internal.v1",
            "deadline_at": (
                datetime.now(timezone.utc) + timedelta(seconds=request.timeout_seconds)
            ).isoformat(),
        }
        return correlation_id, {
            "context": context,
            "input": request.model_dump(mode="json"),
        }

    def _headers_for(self, correlation_id: str) -> dict[str, str]:
        headers = dict(self._headers)
        headers["X-Request-ID"] = correlation_id
        return headers

    @staticmethod
    def _decode(
        response: httpx.Response, correlation_id: str, operation: str
    ) -> SearchOperationResult:
        try:
            if response.is_success:
                envelope = SearchSuccess.model_validate(response.json())
                if envelope.correlation_id != correlation_id:
                    raise ValueError("search response correlation mismatch")
                if envelope.result.operation != operation:
                    raise ValueError("search response operation mismatch")
                return envelope.result
            failure = SearchFailure.model_validate(response.json())
            if failure.correlation_id != correlation_id:
                raise ValueError("search error correlation mismatch")
            raise SearchClientError(
                failure.error.code,
                failure.error.message,
                retryable=failure.error.retryable,
            )
        except SearchClientError:
            raise
        except (ValidationError, ValueError) as exc:
            raise SearchClientError(
                "UPSTREAM_MALFORMED",
                "search service returned an invalid response",
                retryable=False,
            ) from exc

    async def aclose(self) -> None:
        if self._owns_async_client:
            await self._async_client.aclose()
        if self._owns_client:
            self._client.close()


_default_client: SearchClient | None = None


def get_search_client() -> SearchClient:
    global _default_client
    if _default_client is None:
        _default_client = SearchClient()
    return _default_client
