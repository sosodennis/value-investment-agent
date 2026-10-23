"""OpenRouter credential probe with a deliberately small response contract."""

from __future__ import annotations

import httpx

from src.llm_provider_service.domain.errors import OpenRouterKeyTestError


async def test_openrouter_key(
    key: str, *, base_url: str = "https://openrouter.ai/api/v1"
) -> None:
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0)
        ) as client:
            response = await client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {key}"},
            )
    except (httpx.HTTPError, TimeoutError) as exc:
        raise OpenRouterKeyTestError("upstream_unavailable") from exc
    if response.status_code in {401, 403}:
        raise OpenRouterKeyTestError("invalid_key")
    if response.status_code == 429:
        raise OpenRouterKeyTestError("rate_limited")
    if response.status_code >= 500:
        raise OpenRouterKeyTestError("upstream_unavailable")
    if response.status_code >= 400:
        raise OpenRouterKeyTestError("request_rejected")
