from __future__ import annotations

import pytest

import src.infrastructure.llm.provider as provider_module
from src.infrastructure.llm.langchain_adapter import LangChainGatewayModelAdapter


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

    first_model = provider_module.get_llm()
    second_model = provider_module.get_llm()

    assert isinstance(first_model, LangChainGatewayModelAdapter)
    assert isinstance(second_model, LangChainGatewayModelAdapter)
    shared_provider = first_model.provider
    assert second_model.provider is shared_provider

    await provider_module.close_llm_provider()

    assert isinstance(shared_provider, FakeProvider)
    assert shared_provider.closed is True
    assert provider_module._gateway_provider is None
