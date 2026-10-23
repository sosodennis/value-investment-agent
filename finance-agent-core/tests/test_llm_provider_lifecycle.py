from __future__ import annotations

import pytest

import src.llm_provider.entrypoint as provider_module
from src.llm_provider.application import wiring


@pytest.mark.asyncio
async def test_gateway_provider_is_reused_and_closed_at_shutdown(monkeypatch) -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    await provider_module.close_llm_provider()
    monkeypatch.setenv("LLM_PROVIDER_SERVICE_URL", "http://provider:8002")
    monkeypatch.setenv("LLM_PROVIDER_SERVICE_TOKEN", "service-token")
    monkeypatch.setattr(wiring, "LLMProviderServiceClient", FakeProvider)

    first_provider = provider_module.get_llm_provider()
    second_provider = provider_module.get_llm_provider()

    assert isinstance(first_provider, FakeProvider)
    assert second_provider is first_provider

    await provider_module.close_llm_provider()

    assert first_provider.closed is True
    replacement_provider = provider_module.get_llm_provider()
    assert isinstance(replacement_provider, FakeProvider)
    assert replacement_provider is not first_provider
    await provider_module.close_llm_provider()
    assert replacement_provider.closed is True
