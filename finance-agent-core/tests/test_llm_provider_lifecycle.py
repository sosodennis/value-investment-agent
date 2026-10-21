from __future__ import annotations

import pytest

import src.infrastructure.llm.provider as provider_module


@pytest.mark.asyncio
async def test_gateway_provider_is_reused_and_closed_at_shutdown(monkeypatch) -> None:
    class FakeProvider:
        def __init__(self, config: object) -> None:
            self.config = config
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    await provider_module.close_llm_provider()
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway:4000")
    monkeypatch.setattr(provider_module, "LiteLLMGatewayProvider", FakeProvider)

    first_provider = provider_module.get_llm_provider()
    second_provider = provider_module.get_llm_provider()

    assert isinstance(first_provider, FakeProvider)
    assert second_provider is first_provider

    await provider_module.close_llm_provider()

    assert first_provider.closed is True
    assert provider_module._gateway_provider is None
