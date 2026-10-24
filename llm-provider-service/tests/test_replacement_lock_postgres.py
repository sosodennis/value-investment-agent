from __future__ import annotations

import asyncio
import itertools
import os
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from uuid import uuid4

import pytest
from src.llm_provider_service.application.settings_service import (
    ProviderSettingsService,
)
from src.llm_provider_service.domain.errors import ProviderSettingsError
from src.llm_provider_service.domain.provider_models import (
    ManagedProviderKey,
    OpenRouterModel,
)
from src.llm_provider_service.infrastructure.state import ProviderState

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LLM_PROVIDER_POSTGRES_TESTS") != "1",
    reason="requires the isolated PostgreSQL integration database",
)


class _Gateway:
    def __init__(self, old_key_id: str) -> None:
        self.keys = [
            ManagedProviderKey(
                id=old_key_id,
                label="old",
                suffix="1111",
                fingerprint="old-fingerprint",
                created_at=None,
            )
        ]
        self._ids = itertools.count(1)
        self._active_adds = 0
        self.max_active_adds = 0

    async def list_managed(self) -> list[ManagedProviderKey]:
        return list(self.keys)

    async def add_key(
        self,
        *,
        key: str,
        label: str,
        model: str,
        model_name: str,
        existing_ids: set[str],
    ) -> ManagedProviderKey:
        _ = (model, model_name, existing_ids)
        self._active_adds += 1
        self.max_active_adds = max(self.max_active_adds, self._active_adds)
        try:
            await asyncio.sleep(0.05)
        finally:
            self._active_adds -= 1
        identifier = next(self._ids)
        replacement_key = ManagedProviderKey(
            id=f"replacement-{identifier}",
            label=label,
            suffix=key[-4:],
            fingerprint=f"fingerprint-{identifier}",
            created_at=None,
        )
        self.keys.append(replacement_key)
        return replacement_key

    async def mark_replacement_grace(self, key_id: str, *, retire_at: datetime) -> None:
        old_key = next(key for key in self.keys if key.id == key_id)
        self.keys[self.keys.index(old_key)] = replace(
            old_key, replacement_retire_at=retire_at.isoformat()
        )

    async def delete_key(self, key_id: str) -> None:
        self.keys = [key for key in self.keys if key.id != key_id]


class _Settings:
    async def get_selected_model(self) -> str:
        return "openrouter/free"


class _Catalog:
    async def list_free_models(self) -> Sequence[OpenRouterModel]:
        return []

    async def validate_free_model(self, model_id: str) -> bool:
        _ = model_id
        return True


async def _validate_key(key: str) -> None:
    _ = key


@pytest.mark.asyncio
async def test_replacements_serialize_across_independent_postgres_state_clients() -> (
    None
):
    state_one = ProviderState()
    state_two = ProviderState()
    old_key_id = f"old-{uuid4()}"
    user_id = f"user-{uuid4()}"
    try:
        await asyncio.gather(state_one.initialize(), state_two.initialize())
        assert state_one._engine is not state_two._engine
        assert await state_one.claim(
            user_id=user_id,
            resource_type="provider_key",
            resource_id=old_key_id,
            fingerprint=f"fingerprint-{uuid4()}",
        )

        gateway = _Gateway(old_key_id)
        services = (
            ProviderSettingsService(
                gateway=gateway,
                ownership=state_one,
                settings=_Settings(),
                catalog=_Catalog(),
                validate_key=_validate_key,
            ),
            ProviderSettingsService(
                gateway=gateway,
                ownership=state_two,
                settings=_Settings(),
                catalog=_Catalog(),
                validate_key=_validate_key,
            ),
        )
        start = asyncio.Event()

        async def replace_key(
            service: ProviderSettingsService, key: str
        ) -> ManagedProviderKey:
            await start.wait()
            return await service.replace_key(
                user_id=user_id,
                key_id=old_key_id,
                key=key,
                label=key,
            )

        tasks = (
            asyncio.create_task(replace_key(services[0], "key-one")),
            asyncio.create_task(replace_key(services[1], "key-two")),
        )
        start.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert sum(isinstance(result, ManagedProviderKey) for result in results) == 1
        failures = [
            result for result in results if isinstance(result, ProviderSettingsError)
        ]
        assert len(failures) == 1
        assert failures[0].code == "replacement_in_progress"
        assert gateway.max_active_adds == 1
    finally:
        await state_one.close()
        await state_two.close()
