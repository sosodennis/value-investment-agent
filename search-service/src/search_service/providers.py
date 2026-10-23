from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Protocol

import httpx
from pydantic import ValidationError

from .contracts import (
    Capability,
    Operation,
    ProviderCapabilities,
    SearchErrorCode,
    SearchRequestBase,
    SearchResult,
    TimeRange,
)
from .errors import SearchServiceError


class ProviderAdapter(Protocol):
    name: str
    capabilities: ProviderCapabilities

    async def search(
        self,
        *,
        operation: Operation,
        request: SearchRequestBase,
        api_key: str,
        deadline_at: datetime,
    ) -> tuple[SearchResult, ...]: ...

    async def test_key(self, api_key: str, *, deadline_at: datetime) -> bool: ...


def _error(
    code: SearchErrorCode, status: int, message: str, retryable: bool = False
) -> SearchServiceError:
    return SearchServiceError(code, status, message, retryable)


def _map_results(provider: str, rows: object) -> tuple[SearchResult, ...]:
    if not isinstance(rows, list):
        raise _error(
            SearchErrorCode.UPSTREAM_MALFORMED,
            502,
            "provider response could not be normalized",
        )
    mapped: list[SearchResult] = []
    try:
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("result must be an object")
            url = row.get("url") or row.get("href")
            title = row.get("title")
            if not isinstance(url, str) or not isinstance(title, str):
                raise ValueError("result is missing title or url")
            published = row.get("published_at") or row.get("date")
            if isinstance(published, str):
                try:
                    parsed = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    published = parsed.astimezone(UTC) if parsed.tzinfo else None
                except ValueError:
                    published = None
            metadata = {
                str(key): value
                for key, value in row.items()
                if isinstance(value, str | int | float | bool) or value is None
            }
            mapped.append(
                SearchResult(
                    title=title,
                    canonical_url=url,
                    snippet=str(
                        row.get("content")
                        or row.get("body")
                        or row.get("snippet")
                        or ""
                    ),
                    provider=provider,
                    source=row.get("source")
                    if isinstance(row.get("source"), str)
                    else None,
                    published_at=published,
                    image_url=row.get("image")
                    if isinstance(row.get("image"), str)
                    else None,
                    provider_metadata={provider: metadata},
                )
            )
    except (ValueError, ValidationError, TypeError) as exc:
        raise _error(
            SearchErrorCode.UPSTREAM_MALFORMED,
            502,
            "provider response could not be normalized",
        ) from exc
    return tuple(mapped)


class DDGSProvider:
    name = "ddgs"
    capabilities = ProviderCapabilities(
        provider=name,
        operations=frozenset({Operation.WEB, Operation.NEWS}),
        optional_fields=frozenset(
            {Capability.REGION, Capability.TIME_RANGE, Capability.SAFE_SEARCH}
        ),
        key_required=False,
    )

    def __init__(
        self,
        search_call: Callable[..., list[dict[str, object]]] | None = None,
        *,
        max_concurrency: int = 8,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self._search_call = search_call
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrency, thread_name_prefix="ddgs-search"
        )
        self._slots = asyncio.Semaphore(max_concurrency)

    def _search(
        self, operation: Operation, request: SearchRequestBase
    ) -> list[dict[str, object]]:
        call = self._search_call
        if call is None:
            from ddgs import DDGS

            engine = DDGS()
            call = engine.news if operation is Operation.NEWS else engine.text
        region = request.region
        if region == "worldwide":
            region = "wt-wt"
        elif region and "-" in region:
            region = region.split("-")[-1].lower() + "-en"
        else:
            region = "us-en" if region else "wt-wt"
        safesearch = "moderate" if request.safe_search else "off"
        time_map = {
            TimeRange.DAY: "d",
            TimeRange.WEEK: "w",
            TimeRange.MONTH: "m",
            TimeRange.YEAR: "y",
        }
        values = call(
            request.query,
            max_results=request.result_limit,
            region=region,
            safesearch=safesearch,
            timelimit=time_map.get(request.time_range) if request.time_range else None,
        )
        return list(values)

    async def search(
        self,
        *,
        operation: Operation,
        request: SearchRequestBase,
        api_key: str,
        deadline_at: datetime,
    ) -> tuple[SearchResult, ...]:
        del api_key
        timeout = (deadline_at - datetime.now(UTC)).total_seconds()
        if timeout <= 0:
            raise _error(
                SearchErrorCode.DEADLINE_EXCEEDED,
                504,
                "request deadline expired",
                True,
            )
        started_at = asyncio.get_running_loop().time()
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=timeout)
        except TimeoutError as exc:
            raise _error(
                SearchErrorCode.DEADLINE_EXCEEDED,
                504,
                "request deadline expired",
                True,
            ) from exc
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self._executor, self._search, operation, request)

        def release_after_worker(_: asyncio.Future[list[dict[str, object]]]) -> None:
            loop.call_soon_threadsafe(self._slots.release)

        remaining = timeout - (loop.time() - started_at)
        try:
            rows = await asyncio.wait_for(asyncio.shield(future), timeout=remaining)
        except TimeoutError as exc:
            future.add_done_callback(release_after_worker)
            raise _error(
                SearchErrorCode.DEADLINE_EXCEEDED,
                504,
                "request deadline expired",
                True,
            ) from exc
        except asyncio.CancelledError:
            future.add_done_callback(release_after_worker)
            raise
        except Exception as exc:
            self._slots.release()
            raise _error(
                SearchErrorCode.UPSTREAM_UNAVAILABLE,
                503,
                "DDGS search is unavailable",
                True,
            ) from exc
        else:
            self._slots.release()
        return _map_results(self.name, rows)

    async def test_key(self, api_key: str, *, deadline_at: datetime) -> bool:
        del api_key, deadline_at
        return True


class TavilyProvider:
    name = "tavily"
    capabilities = ProviderCapabilities(
        provider=name,
        operations=frozenset({Operation.WEB, Operation.NEWS}),
        optional_fields=frozenset({Capability.REGION, Capability.TIME_RANGE}),
        key_required=True,
    )

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.tavily.com/search",
    ) -> None:
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._base_url = base_url

    def _payload(
        self, operation: Operation, request: SearchRequestBase
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "query": request.query,
            "topic": "news" if operation is Operation.NEWS else "general",
            "search_depth": "basic",
            "max_results": request.result_limit,
            "include_answer": False,
            "include_raw_content": False,
        }
        if request.region and request.region != "worldwide":
            payload["country"] = request.region.split("-")[-1]
        if request.time_range:
            payload["days"] = {
                TimeRange.DAY: 1,
                TimeRange.WEEK: 7,
                TimeRange.MONTH: 30,
                TimeRange.YEAR: 365,
            }[request.time_range]
        return payload

    async def _post(
        self, api_key: str, payload: dict[str, object], deadline_at: datetime
    ) -> object:
        timeout = (deadline_at - datetime.now(UTC)).total_seconds()
        if timeout <= 0:
            raise _error(
                SearchErrorCode.DEADLINE_EXCEEDED,
                504,
                "request deadline expired",
                True,
            )
        try:
            authenticated_payload = {**payload, "api_key": api_key}
            response = await self._client.post(
                self._base_url,
                json=authenticated_payload,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise _error(
                SearchErrorCode.DEADLINE_EXCEEDED,
                504,
                "request deadline expired",
                True,
            ) from exc
        except httpx.HTTPError as exc:
            raise _error(
                SearchErrorCode.UPSTREAM_UNAVAILABLE,
                503,
                "Tavily is unavailable",
                True,
            ) from exc
        if response.status_code == 401 or response.status_code == 403:
            raise _error(
                SearchErrorCode.AUTHENTICATION_FAILED,
                422,
                "provider key was rejected",
            )
        if response.status_code == 429:
            raise _error(
                SearchErrorCode.RATE_LIMITED, 429, "provider rate limit reached", True
            )
        if response.status_code >= 500:
            raise _error(
                SearchErrorCode.UPSTREAM_UNAVAILABLE, 503, "Tavily is unavailable", True
            )
        if response.status_code >= 400:
            raise _error(
                SearchErrorCode.UPSTREAM_MALFORMED, 502, "Tavily rejected the request"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise _error(
                SearchErrorCode.UPSTREAM_MALFORMED,
                502,
                "provider response could not be normalized",
            ) from exc

    async def search(
        self,
        *,
        operation: Operation,
        request: SearchRequestBase,
        api_key: str,
        deadline_at: datetime,
    ) -> tuple[SearchResult, ...]:
        data = await self._post(api_key, self._payload(operation, request), deadline_at)
        if not isinstance(data, Mapping):
            raise _error(
                SearchErrorCode.UPSTREAM_MALFORMED,
                502,
                "provider response could not be normalized",
            )
        return _map_results(self.name, data.get("results"))

    async def test_key(self, api_key: str, *, deadline_at: datetime) -> bool:
        try:
            await self._post(api_key, {"query": "test", "max_results": 1}, deadline_at)
        except SearchServiceError as exc:
            if exc.code == "AUTHENTICATION_FAILED":
                return False
            raise
        return True

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
