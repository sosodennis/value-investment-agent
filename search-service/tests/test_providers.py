from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from search_service.contracts import Capability, Operation, WebSearchRequest
from search_service.errors import SearchServiceError
from search_service.postgres_control_plane import PostgresSearchControlPlane
from search_service.providers import DDGSProvider, TavilyProvider


@pytest.mark.asyncio
async def test_tavily_maps_web_results_into_the_search_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Example",
                        "url": "https://example.test/story",
                        "content": "Summary",
                        "score": 0.8,
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TavilyProvider(client=client, base_url="https://tavily.test/search")
    results = await provider.search(
        operation=Operation.WEB,
        request=WebSearchRequest(query="sample", region="en-US", result_limit=5),
        api_key="test-key",
        deadline_at=datetime.now(UTC) + timedelta(seconds=2),
    )
    await client.aclose()
    assert provider.capabilities.optional_fields == frozenset(
        {Capability.REGION, Capability.TIME_RANGE}
    )
    assert requests[0].read().decode().find('"api_key":"test-key"') >= 0
    assert results[0].model_dump(mode="json") == {
        "title": "Example",
        "canonical_url": "https://example.test/story",
        "snippet": "Summary",
        "provider": "tavily",
        "source": None,
        "published_at": None,
        "image_url": None,
        "provider_metadata": {
            "tavily": {
                "title": "Example",
                "url": "https://example.test/story",
                "content": "Summary",
                "score": 0.8,
            }
        },
    }


@pytest.mark.asyncio
async def test_tavily_maps_rate_limit_without_leaking_credentials() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(429))
    )
    provider = TavilyProvider(client=client, base_url="https://tavily.test/search")
    with pytest.raises(SearchServiceError) as raised:
        await provider.search(
            operation=Operation.WEB,
            request=WebSearchRequest(query="private query"),
            api_key="secret-key",
            deadline_at=datetime.now(UTC) + timedelta(seconds=2),
        )
    await client.aclose()
    assert raised.value.code == "RATE_LIMITED"
    assert "secret-key" not in str(raised.value)
    assert "private query" not in str(raised.value)


@pytest.mark.asyncio
async def test_ddgs_timeout_keeps_worker_capacity_reserved_until_completion() -> None:
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def blocking_search(_query: str, **_: object) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=2)
        return []

    provider = DDGSProvider(search_call=blocking_search, max_concurrency=1)
    with pytest.raises(SearchServiceError) as raised:
        await provider.search(
            operation=Operation.WEB,
            request=WebSearchRequest(query="first"),
            api_key="",
            deadline_at=datetime.now(UTC) + timedelta(milliseconds=50),
        )
    assert raised.value.code == "DEADLINE_EXCEEDED"
    assert started.is_set()

    second = asyncio.create_task(
        provider.search(
            operation=Operation.WEB,
            request=WebSearchRequest(query="second"),
            api_key="",
            deadline_at=datetime.now(UTC) + timedelta(seconds=1),
        )
    )
    await asyncio.sleep(0.1)
    assert calls == 1
    release.set()
    assert await second == ()
    assert calls == 2


def test_ddgs_advertises_only_supported_capabilities() -> None:
    provider = DDGSProvider(search_call=lambda **_: [])
    assert provider.capabilities.operations == frozenset(
        {Operation.WEB, Operation.NEWS}
    )
    assert provider.capabilities.optional_fields == frozenset(
        {Capability.REGION, Capability.TIME_RANGE, Capability.SAFE_SEARCH}
    )


def test_postgres_control_plane_requires_service_encryption_key() -> None:
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode("ascii")
    store = PostgresSearchControlPlane("postgresql://unused", key)
    assert store._decrypt(store._cipher.encrypt(b"raw-provider-key").decode()) == (
        "raw-provider-key"
    )
    with pytest.raises(ValueError, match="Fernet key"):
        PostgresSearchControlPlane("postgresql://unused", "not-a-valid-key")
    with pytest.raises(ValueError, match="database URL and encryption key"):
        PostgresSearchControlPlane("postgresql://unused", "")


@pytest.mark.asyncio
async def test_search_encryption_rotation_rejects_invalid_replacement_key() -> None:
    from cryptography.fernet import Fernet

    old_key = Fernet.generate_key().decode("ascii")
    store = PostgresSearchControlPlane("postgresql://unused", old_key)
    with pytest.raises(ValueError, match="Fernet keys"):
        await store.rotate_encryption_key(old_key=old_key, new_key="not-a-valid-key")
