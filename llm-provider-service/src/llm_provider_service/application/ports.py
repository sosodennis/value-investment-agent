from __future__ import annotations

from collections.abc import Collection, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from src.llm_provider_service.domain.provider_models import (
    ManagedProviderKey,
    OpenRouterModel,
    ProviderKeyHealth,
)


class KeyGateway(Protocol):
    async def list_managed(self) -> list[ManagedProviderKey]: ...

    async def add_key(
        self,
        *,
        key: str,
        label: str,
        model: str,
        model_name: str,
        existing_ids: Collection[str],
    ) -> ManagedProviderKey: ...

    async def update_model(self, model: str) -> None: ...

    async def test_key(self, model_id: str) -> bool: ...

    async def mark_replacement_grace(
        self, model_id: str, *, retire_at: datetime
    ) -> None: ...

    async def delete_key(self, model_id: str) -> None: ...


class OwnershipPort(Protocol):
    def replacement_lock(
        self, *, user_id: str, key_id: str
    ) -> AbstractAsyncContextManager[None]: ...

    def fingerprint_lock(
        self, *, user_id: str, fingerprint: str
    ) -> AbstractAsyncContextManager[None]: ...

    async def claim(
        self,
        *,
        user_id: str,
        resource_type: str,
        resource_id: str,
        fingerprint: str | None = None,
    ) -> bool: ...

    async def owns(
        self,
        *,
        user_id: str,
        resource_type: str,
        resource_id: str,
    ) -> bool: ...

    async def owned_ids(self, *, user_id: str, resource_type: str) -> set[str]: ...

    async def release(self, *, resource_type: str, resource_id: str) -> None: ...

    async def find_by_fingerprint(
        self, *, user_id: str, fingerprint: str
    ) -> str | None: ...


class SelectedModelSettings(Protocol):
    async def get_selected_model(self) -> str: ...

    async def set_selected_model(self, model_id: str, *, updated_by: str) -> str: ...


class ModelCatalog(Protocol):
    async def list_free_models(self) -> Sequence[OpenRouterModel]: ...

    async def validate_free_model(self, model_id: str) -> bool: ...


class OpenRouterKeyValidator(Protocol):
    async def __call__(self, key: str) -> None: ...


class ProviderKeyTelemetry(Protocol):
    async def get_many(
        self, key_ids: Collection[str]
    ) -> dict[str, ProviderKeyHealth]: ...

    async def delete(self, key_id: str) -> None: ...
