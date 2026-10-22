from __future__ import annotations

import os

from src.auth.entrypoint import get_ownership_service
from src.llm_provider.application.settings_service import ProviderSettingsService
from src.llm_provider.domain.contracts import LLMProviderPort, ModelRoute
from src.llm_provider.domain.routes import DEFAULT_MODEL_ALIAS
from src.llm_provider.infrastructure.gateway import (
    LiteLLMGatewayConfig,
    LiteLLMGatewayProvider,
)
from src.llm_provider.infrastructure.key_telemetry import RedisProviderKeyTelemetry
from src.llm_provider.infrastructure.litellm_admin import LiteLLMAdminClient
from src.llm_provider.infrastructure.openrouter_key_test import test_openrouter_key
from src.llm_provider.infrastructure.openrouter_models import (
    list_free_models,
    validate_free_model,
)
from src.llm_provider.infrastructure.settings import (
    get_selected_model,
    set_selected_model,
)

MODEL_ROUTE_ALIAS = DEFAULT_MODEL_ALIAS
_gateway_provider: LiteLLMGatewayProvider | None = None
_key_telemetry: RedisProviderKeyTelemetry | None = None


def get_provider_key_telemetry() -> RedisProviderKeyTelemetry:
    global _key_telemetry
    if _key_telemetry is None:
        _key_telemetry = RedisProviderKeyTelemetry()
    return _key_telemetry


def get_llm_provider() -> LLMProviderPort:
    global _gateway_provider
    if _gateway_provider is None:
        _gateway_provider = LiteLLMGatewayProvider(LiteLLMGatewayConfig.from_env())
    return _gateway_provider


def get_default_model_route() -> ModelRoute:
    return ModelRoute(alias=MODEL_ROUTE_ALIAS)


async def close_llm_provider() -> None:
    global _gateway_provider, _key_telemetry
    provider = _gateway_provider
    _gateway_provider = None
    if provider is not None:
        await provider.aclose()
    telemetry = _key_telemetry
    _key_telemetry = None
    if telemetry is not None:
        await telemetry.close()


class _OpenRouterCatalog:
    async def list_free_models(self):
        return await list_free_models()

    async def validate_free_model(self, model_id: str) -> bool:
        return await validate_free_model(model_id)


def get_provider_settings_service() -> ProviderSettingsService:
    base_url = os.getenv("LLM_GATEWAY_BASE_URL", "http://localhost:4000").strip()
    token = os.getenv("LLM_GATEWAY_API_KEY", "").strip()
    openrouter_headers = {
        "X-Title": os.getenv("OPENROUTER_X_TITLE", "Value Investment Agent")
    }
    referer = os.getenv("OPENROUTER_HTTP_REFERER", "").strip()
    if referer:
        openrouter_headers["HTTP-Referer"] = referer
    return ProviderSettingsService(
        gateway=LiteLLMAdminClient(
            base_url=base_url,
            admin_token=token,
            openrouter_headers=openrouter_headers,
        ),
        ownership=get_ownership_service(),
        settings=_SelectedModelSettings(),
        catalog=_OpenRouterCatalog(),
        validate_key=test_openrouter_key,
        telemetry=get_provider_key_telemetry(),
    )


class _SelectedModelSettings:
    async def get_selected_model(self) -> str:
        return await get_selected_model()

    async def set_selected_model(self, model_id: str, *, updated_by: str) -> str:
        return await set_selected_model(model_id, updated_by=updated_by)
