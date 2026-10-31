from __future__ import annotations

import os
from contextlib import AbstractAsyncContextManager

from src.llm_provider_service.application.key_import_service import (
    ProviderKeyImportService,
)
from src.llm_provider_service.application.ports import ModelCatalog
from src.llm_provider_service.application.settings_service import (
    ProviderSettingsService,
)
from src.llm_provider_service.infrastructure.embedded_runtime import (
    EmbeddedLiteLLMProvider,
)
from src.llm_provider_service.infrastructure.key_telemetry import (
    RedisProviderKeyTelemetry,
)
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

    def fingerprint_lock(
        self, *, user_id: str, fingerprint: str
    ) -> AbstractAsyncContextManager[None]:
        return self._state.fingerprint_lock(user_id=user_id, fingerprint=fingerprint)

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
        encryption_key = os.getenv("LLM_PROVIDER_ENCRYPTION_KEY", "").strip()
        if not encryption_key:
            raise ValueError(
                "LLM_PROVIDER_ENCRYPTION_KEY is required for the LLM provider service"
            )
        self.state = ProviderState(encryption_key=encryption_key)
        self.telemetry: RedisProviderKeyTelemetry | None = None
        self.provider: EmbeddedLiteLLMProvider | None = None
        self.settings: ProviderSettingsService | None = None
        self.imports: ProviderKeyImportService | None = None
        self.ready = False

    async def start(self) -> None:
        await self.state.initialize()
        self.telemetry = RedisProviderKeyTelemetry()
        self.provider = EmbeddedLiteLLMProvider(self.state)
        await self.provider.start()
        self.settings = ProviderSettingsService(
            gateway=self.provider,
            ownership=_Ownership(self.state),
            settings=_Settings(self.state),
            catalog=_Catalog(),
            validate_key=validate_openrouter_key,
            telemetry=self.telemetry,
        )
        self.imports = ProviderKeyImportService(
            state=self.state,
            provider=self.provider,
        )
        await self.imports.start()
        self.ready = True

    async def close(self) -> None:
        self.ready = False
        if self.imports is not None:
            await self.imports.close()
        if self.provider is not None:
            await self.provider.aclose()
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
