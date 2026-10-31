from __future__ import annotations

import os
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from src.llm_provider_service.domain.errors import OpenRouterKeyTestError


async def validate_openrouter_key(
    key: str,
    *,
    base_url: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> None:
    endpoint = (
        base_url or os.getenv("OPENROUTER_API_BASE_URL", "https://openrouter.ai/api/v1")
    ).rstrip("/")
    try:
        if client is None:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0)
            ) as owned_client:
                response = await owned_client.get(
                    f"{endpoint}/key",
                    headers={"Authorization": f"Bearer {key}"},
                )
        else:
            response = await client.get(
                f"{endpoint}/key",
                headers={"Authorization": f"Bearer {key}"},
            )
    except (httpx.HTTPError, TimeoutError) as exc:
        raise OpenRouterKeyTestError("upstream_unavailable") from exc
    if response.status_code in {401, 403}:
        raise OpenRouterKeyTestError("invalid_key")
    if response.status_code == 429:
        raise OpenRouterKeyTestError(
            "rate_limited", retry_after_seconds=_retry_after_seconds(response)
        )
    if response.status_code >= 500:
        raise OpenRouterKeyTestError("upstream_unavailable")
    if response.status_code >= 400:
        raise OpenRouterKeyTestError("request_rejected")


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return min(max(0.0, float(value)), 60.0)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return min(max(0.0, (retry_at - datetime.now(UTC)).total_seconds()), 60.0)
