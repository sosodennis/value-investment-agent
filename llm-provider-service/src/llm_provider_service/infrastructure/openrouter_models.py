"""OpenRouter model catalogue access and free-model policy."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping

import httpx

from src.llm_provider_service.domain.errors import OpenRouterModelsError
from src.llm_provider_service.domain.provider_models import OpenRouterModel

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
FREE_ROUTER_ID = "openrouter/free"
_CACHE_TTL_SECONDS = 300.0


_cache: tuple[float, tuple[OpenRouterModel, ...]] | None = None
_cache_lock = asyncio.Lock()


def _is_zero_price(value: object) -> bool:
    if isinstance(value, int | float):
        return value == 0
    if isinstance(value, str):
        try:
            return float(value) == 0
        except ValueError:
            return False
    return False


def _parse_model(value: object) -> OpenRouterModel | None:
    if not isinstance(value, Mapping):
        return None
    model_id = value.get("id")
    name = value.get("name")
    pricing = value.get("pricing")
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    if not isinstance(name, str) or not name.strip():
        name = model_id
    if not isinstance(pricing, Mapping):
        return None
    # OpenRouter's catalogue can report zero text-token pricing for models
    # whose other modalities are paid. The `:free` suffix is the provider's
    # explicit availability contract, so use it as the UI's free-model gate.
    if model_id != FREE_ROUTER_ID and not (
        model_id.endswith(":free")
        and _is_zero_price(pricing.get("prompt"))
        and _is_zero_price(pricing.get("completion"))
    ):
        return None
    context = value.get("context_length")
    context_length = context if isinstance(context, int) and context > 0 else None
    description = value.get("description")
    return OpenRouterModel(
        id=model_id,
        name=name,
        description=description if isinstance(description, str) else None,
        context_length=context_length,
    )


def _parse_catalog(payload: object) -> tuple[OpenRouterModel, ...]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        raise OpenRouterModelsError("OpenRouter returned an invalid model catalogue")
    models = [model for raw in payload["data"] if (model := _parse_model(raw))]
    models.sort(
        key=lambda model: (model.id != FREE_ROUTER_ID, model.name.lower(), model.id)
    )
    if not any(model.id == FREE_ROUTER_ID for model in models):
        models.insert(
            0,
            OpenRouterModel(
                id=FREE_ROUTER_ID,
                name="Free Models Router",
                description="OpenRouter selects an available free model for each request.",
                context_length=None,
            ),
        )
    return tuple(models)


async def list_free_models(
    *, client: httpx.AsyncClient | None = None
) -> tuple[OpenRouterModel, ...]:
    """Return a short-lived, validated catalogue of zero-cost chat models."""
    global _cache
    use_cache = client is None
    now = time.monotonic()
    if use_cache and _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    owns_client = client is None
    request_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=3.0)
    )
    try:
        async with _cache_lock:
            now = time.monotonic()
            if (
                use_cache
                and _cache is not None
                and now - _cache[0] < _CACHE_TTL_SECONDS
            ):
                return _cache[1]
            try:
                response = await request_client.get(
                    OPENROUTER_MODELS_URL,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                models = _parse_catalog(response.json())
            except (httpx.HTTPError, ValueError, OpenRouterModelsError) as exc:
                if use_cache and _cache is not None:
                    return _cache[1]
                raise OpenRouterModelsError(
                    "OpenRouter model catalogue is unavailable"
                ) from exc
            if use_cache:
                _cache = (time.monotonic(), models)
            return models
    finally:
        if owns_client:
            await request_client.aclose()


async def validate_free_model(model_id: str) -> bool:
    return any(model.id == model_id for model in await list_free_models())
