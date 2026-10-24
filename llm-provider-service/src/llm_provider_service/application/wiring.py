from __future__ import annotations

import os
from contextlib import AbstractAsyncContextManager

from src.llm_provider_service.application.ports import ModelCatalog
from src.llm_provider_service.application.settings_service import (
    ProviderSettingsService,
)
from src.llm_provider_service.domain.contracts import LLMProviderPort
from src.llm_provider_service.infrastructure.gateway import (
    LiteLLMGatewayConfig,
    LiteLLMGatewayProvider,
)
from src.llm_provider_service.infrastructure.key_telemetry import (
    RedisProviderKeyTelemetry,
)
from src.llm_provider_service.infrastructure.litellm_admin import LiteLLMAdminClient
from src.llm_provider_service.infrastructure.openrouter_key_test import (
    validate_openrouter_key,
)
from src.llm_provider_service.infrastructure.openrouter_models import (
    list_free_models,
    validate_free_model,
)
from src.llm_provider_service.infrastructure.state import ProviderState


class _Ownership:
    def __init__(self, state: ProviderState) -> None:
        self._state = state

    def replacement_lock(
        self, *, user_id: str, key_id: str
    ) -> AbstractAsyncContextManager[None]:
        return self._state.replacement_lock(user_id=user_id, key_id=key_id)

    async def claim(
        self,
        *,
        user_id: str,
        resource_type: str,
        resource_id: str,
        fingerprint: str | None = None,
    ) -> bool:
        return await self._state.claim(
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            fingerprint=fingerprint,
        )

    async def owns(self, *, user_id: str, resource_type: str, resource_id: str) -> bool:
        return await self._state.owns(
            user_id=user_id, resource_type=resource_type, resource_id=resource_id
        )

    async def owned_ids(self, *, user_id: str, resource_type: str) -> set[str]:
        return await self._state.owned_ids(user_id=user_id, resource_type=resource_type)

    async def release(self, *, resource_type: str, resource_id: str) -> None:
        await self._state.release(resource_type=resource_type, resource_id=resource_id)

    async def find_by_fingerprint(
        self, *, user_id: str, fingerprint: str
    ) -> str | None:
        return await self._state.find_by_fingerprint(
            user_id=user_id, fingerprint=fingerprint
        )


class _Settings:
    def __init__(self, state: ProviderState) -> None:
        self._state = state

    async def get_selected_model(self) -> str:
        return await self._state.get_selected_model()

    async def set_selected_model(self, model_id: str, *, updated_by: str) -> str:
        return await self._state.set_selected_model(model_id, updated_by=updated_by)


class _Catalog(ModelCatalog):
    async def list_free_models(self):
        return await list_free_models()

    async def validate_free_model(self, model_id: str) -> bool:
        return await validate_free_model(model_id)


class ProviderRuntime:
    def __init__(self) -> None:
        self.state = ProviderState()
        base_url = os.getenv("LLM_GATEWAY_BASE_URL", "http://localhost:4000").strip()
        token = os.getenv("LLM_GATEWAY_API_KEY", "").strip()
        headers = {"X-Title": os.getenv("OPENROUTER_X_TITLE", "Value Investment Agent")}
        referer = os.getenv("OPENROUTER_HTTP_REFERER", "").strip()
        if referer:
            headers["HTTP-Referer"] = referer
        self.admin = LiteLLMAdminClient(
            base_url=base_url, admin_token=token, openrouter_headers=headers
        )
        self.telemetry: RedisProviderKeyTelemetry | None = None
        self.gateway: LLMProviderPort | None = None
        self.settings: ProviderSettingsService | None = None
        self.ready = False

    async def start(self) -> None:
        await self.state.initialize()
        self.telemetry = RedisProviderKeyTelemetry()
        self.gateway = LiteLLMGatewayProvider(LiteLLMGatewayConfig.from_env())
        self.settings = ProviderSettingsService(
            gateway=self.admin,
            ownership=_Ownership(self.state),
            settings=_Settings(self.state),
            catalog=_Catalog(),
            validate_key=validate_openrouter_key,
            telemetry=self.telemetry,
        )
        self.ready = True

    async def close(self) -> None:
        self.ready = False
        if self.gateway is not None:
            await self.gateway.aclose()
        await self.admin.close()
        if self.telemetry is not None:
            await self.telemetry.close()
        await self.state.close()

    async def synchronize_model(self) -> None:
        if self.settings is not None:
            await self.settings.synchronize_selected_model()

    async def cleanup_replacements(self) -> int:
        if self.settings is None:
            return 0
        return await self.settings.cleanup_expired_replacements()
