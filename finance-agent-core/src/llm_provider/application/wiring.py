from __future__ import annotations

from src.llm_provider.domain.contracts import LLMProviderPort, ModelRoute
from src.llm_provider.domain.routes import DEFAULT_MODEL_ALIAS
from src.llm_provider.infrastructure.remote_client import (
    LLMProviderServiceClient,
    LLMProviderServiceSettingsClient,
)

MODEL_ROUTE_ALIAS = DEFAULT_MODEL_ALIAS
_gateway_provider: LLMProviderPort | None = None
_settings_client: LLMProviderServiceSettingsClient | None = None


def get_llm_provider() -> LLMProviderPort:
    global _gateway_provider
    if _gateway_provider is None:
        _gateway_provider = LLMProviderServiceClient()
    return _gateway_provider


def get_default_model_route() -> ModelRoute:
    return ModelRoute(alias=MODEL_ROUTE_ALIAS)


async def close_llm_provider() -> None:
    global _gateway_provider, _settings_client
    provider = _gateway_provider
    _gateway_provider = None
    if provider is not None:
        await provider.aclose()
    settings_client = _settings_client
    _settings_client = None
    if settings_client is not None:
        await settings_client.aclose()


def get_provider_settings_service() -> LLMProviderServiceSettingsClient:
    global _settings_client
    if _settings_client is None:
        _settings_client = LLMProviderServiceSettingsClient()
    return _settings_client
