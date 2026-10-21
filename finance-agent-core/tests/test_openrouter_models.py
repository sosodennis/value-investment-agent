from __future__ import annotations

import httpx
import pytest

from src.infrastructure.llm.openrouter_models import (
    FREE_ROUTER_ID,
    list_free_models,
)


@pytest.mark.asyncio
async def test_catalog_filters_to_zero_cost_models_and_keeps_router() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "openrouter/free",
                        "name": "Free Models Router",
                        "pricing": {"prompt": "0", "completion": "0"},
                    },
                    {
                        "id": "provider/free-model:free",
                        "name": "Free Model",
                        "pricing": {"prompt": 0, "completion": "0"},
                    },
                    {
                        "id": "provider/paid-model",
                        "name": "Paid Model",
                        "pricing": {"prompt": "0.000001", "completion": "0"},
                    },
                    {
                        "id": "provider/paid-audio-model",
                        "name": "Paid Audio Model",
                        "pricing": {"prompt": "0", "completion": "0"},
                    },
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    models = await list_free_models(client=client)
    await client.aclose()

    assert [model.id for model in models] == [
        FREE_ROUTER_ID,
        "provider/free-model:free",
    ]
