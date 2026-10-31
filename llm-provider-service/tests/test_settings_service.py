from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime

import pytest
from src.llm_provider_service.application.settings_service import (
    ProviderSettingsService,
)
from src.llm_provider_service.domain.errors import ProviderSettingsError
from src.llm_provider_service.domain.key_metadata import key_fingerprint
from src.llm_provider_service.domain.provider_models import ManagedProviderKey


class _Gateway:
    def __init__(self) -> None:
        self.keys = [
            ManagedProviderKey(
                id="old-key",
                label="old",
                suffix="1111",
                fingerprint="old-fingerprint",
                created_at=None,
            )
        ]
        self.grace_calls = 0
        self._next_id = 0

    async def list_managed(self) -> list[ManagedProviderKey]:
        return list(self.keys)

    async def add_replacement_key(
        self,
        *,
        key: str,
        label: str,
        model: str,
        model_name: str,
        existing_ids: set[str],
    ) -> ManagedProviderKey:
        _ = (model, model_name, existing_ids)
        self._next_id += 1
        replacement = ManagedProviderKey(
            id=f"replacement-{self._next_id}",
            label=label,
            suffix=key[-4:],
            fingerprint=f"fingerprint-{self._next_id}",
            created_at=None,
        )
        self.keys.append(replacement)
        return replacement

    async def mark_replacement_grace(
        self, model_id: str, *, retire_at: datetime
    ) -> None:
        self.grace_calls += 1
        old = next(key for key in self.keys if key.id == model_id)
        self.keys[self.keys.index(old)] = replace(
            old, replacement_retire_at=retire_at.isoformat()
        )

    async def delete_key(self, model_id: str) -> None:
        self.keys = [key for key in self.keys if key.id != model_id]


class _Ownership:
    def __init__(self) -> None:
        self.ids = {"old-key"}
        self.lock = asyncio.Lock()
        self.fingerprint_locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def replacement_lock(
        self, *, user_id: str, key_id: str
    ) -> AsyncIterator[None]:
        _ = (user_id, key_id)
        async with self.lock:
            yield

    @asynccontextmanager
    async def fingerprint_lock(
        self, *, user_id: str, fingerprint: str
    ) -> AsyncIterator[None]:
        _ = user_id
        lock = self.fingerprint_locks.setdefault(fingerprint, asyncio.Lock())
        async with lock:
            yield

    async def owns(self, *, user_id: str, resource_type: str, resource_id: str) -> bool:
        _ = (user_id, resource_type)
        return resource_id in self.ids

    async def owned_ids(self, *, user_id: str, resource_type: str) -> set[str]:
        _ = (user_id, resource_type)
        return set(self.ids)

    async def claim(
        self,
        *,
        user_id: str,
        resource_type: str,
        resource_id: str,
        fingerprint: str | None = None,
    ) -> bool:
        _ = (user_id, resource_type, fingerprint)
        if resource_id in self.ids:
            return False
        self.ids.add(resource_id)
        return True

    async def release(self, *, resource_type: str, resource_id: str) -> None:
        _ = resource_type
        self.ids.discard(resource_id)

    async def find_by_fingerprint(
        self, *, user_id: str, fingerprint: str
    ) -> str | None:
        _ = (user_id, fingerprint)
        return None


class _Settings:
    async def get_selected_model(self) -> str:
        return "openrouter/free"

    async def set_selected_model(self, model_id: str, *, updated_by: str) -> str:
        _ = updated_by
        return model_id


class _Catalog:
    async def list_free_models(self):
        return []

    async def validate_free_model(self, model_id: str) -> bool:
        _ = model_id
        return True


async def _validate_key(key: str) -> None:
    _ = key


@pytest.mark.asyncio
async def test_concurrent_replacements_have_one_winner() -> None:
    gateway = _Gateway()
    service = ProviderSettingsService(
        gateway=gateway,
        ownership=_Ownership(),
        settings=_Settings(),
        catalog=_Catalog(),
        validate_key=_validate_key,
    )

    results = await asyncio.gather(
        service.replace_key(
            user_id="alice", key_id="old-key", key="key-one", label="one"
        ),
        service.replace_key(
            user_id="alice", key_id="old-key", key="key-two", label="two"
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(result, ManagedProviderKey) for result in results) == 1
    assert (
        sum(
            isinstance(result, ProviderSettingsError)
            and result.code == "replacement_in_progress"
            for result in results
        )
        == 1
    )
    assert gateway.grace_calls == 1


@pytest.mark.asyncio
async def test_replacement_rejects_the_current_key_without_mutating_gateway() -> None:
    gateway = _Gateway()
    same_key = "same-openrouter-key"
    gateway.keys[0] = replace(gateway.keys[0], fingerprint=key_fingerprint(same_key))
    service = ProviderSettingsService(
        gateway=gateway,
        ownership=_Ownership(),
        settings=_Settings(),
        catalog=_Catalog(),
        validate_key=_validate_key,
    )

    with pytest.raises(ProviderSettingsError) as caught:
        await service.replace_key(
            user_id="alice", key_id="old-key", key=same_key, label="same"
        )

    assert caught.value.code == "replacement_must_differ"
    assert len(gateway.keys) == 1
    assert gateway.grace_calls == 0
