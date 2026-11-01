from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from src.llm_provider_service.application.ports import (
    KeyGateway,
    ModelCatalog,
    OpenRouterKeyValidator,
    OwnershipPort,
    ProviderKeyTelemetry,
    SelectedModelSettings,
)
from src.llm_provider_service.domain.errors import (
    OpenRouterKeyTestError,
    OpenRouterModelsError,
    ProviderSettingsError,
)
from src.llm_provider_service.domain.key_metadata import (
    key_fingerprint,
    validate_model_id,
)
from src.llm_provider_service.domain.provider_models import (
    ManagedProviderKey,
    OpenRouterModel,
)
from src.llm_provider_service.domain.routes import organization_route_alias

RESOURCE_TYPE = "provider_key"


class ProviderSettingsService:
    def __init__(
        self,
        *,
        gateway: KeyGateway,
        ownership: OwnershipPort,
        settings: SelectedModelSettings,
        catalog: ModelCatalog,
        validate_key: OpenRouterKeyValidator,
        telemetry: ProviderKeyTelemetry | None = None,
    ) -> None:
        self._gateway = gateway
        self._ownership = ownership
        self._settings = settings
        self._catalog = catalog
        self._validate_key = validate_key
        self._telemetry = telemetry

    async def list_keys(self, *, organization_id: str) -> list[ManagedProviderKey]:
        owned_ids = await self._ownership.owned_ids(
            organization_id=organization_id, resource_type=RESOURCE_TYPE
        )
        keys = [
            key
            for key in await self._gateway.list_managed(organization_id=organization_id)
            if key.id in owned_ids
        ]
        for key in keys:
            await self._ownership.claim(
                organization_id=organization_id,
                resource_type=RESOURCE_TYPE,
                resource_id=key.id,
                fingerprint=key.fingerprint,
            )
        if self._telemetry is None or not keys:
            return keys
        health_by_id = await self._telemetry.get_many(
            {key.id for key in keys}, organization_id=organization_id
        )
        return [
            replace(
                key,
                status=health.status,
                failure_count=health.failure_count,
                cooldown_until=health.cooldown_until,
                last_error=health.last_error,
                last_used_at=health.last_used_at,
            )
            if (health := health_by_id.get(key.id)) is not None
            else key
            for key in keys
        ]

    async def replace_key(
        self, *, organization_id: str, key_id: str, key: str, label: str
    ) -> ManagedProviderKey:
        try:
            key_id = validate_model_id(key_id)
        except ValueError as exc:
            raise ProviderSettingsError("invalid_key_id") from exc
        async with self._ownership.replacement_lock(
            organization_id=organization_id, key_id=key_id
        ):
            if not await self._ownership.owns(
                organization_id=organization_id,
                resource_type=RESOURCE_TYPE,
                resource_id=key_id,
            ):
                raise ProviderSettingsError("not_found")
            existing_keys = await self._gateway.list_managed(
                organization_id=organization_id
            )
            old_key = next((item for item in existing_keys if item.id == key_id), None)
            if old_key is None:
                raise ProviderSettingsError("not_found")
            if old_key.replacement_retire_at is not None:
                raise ProviderSettingsError("replacement_in_progress")
            if old_key.fingerprint == key_fingerprint(key):
                raise ProviderSettingsError("replacement_must_differ")
            await self._test_key_material(key)

            owned_ids = await self._ownership.owned_ids(
                organization_id=organization_id, resource_type=RESOURCE_TYPE
            )
            replacement = await self._gateway.add_replacement_key(
                key=key,
                label=label,
                model=await self._settings.get_selected_model(
                    organization_id=organization_id
                ),
                model_name=organization_route_alias(organization_id),
                organization_id=organization_id,
                existing_ids=owned_ids,
            )
            if not await self._ownership.claim(
                organization_id=organization_id,
                resource_type=RESOURCE_TYPE,
                resource_id=replacement.id,
                fingerprint=replacement.fingerprint,
            ):
                if replacement.id not in owned_ids:
                    await self._gateway.delete_key(
                        replacement.id, organization_id=organization_id
                    )
                raise ProviderSettingsError("already_owned")
            grace_seconds = min(
                3600,
                max(60, int(os.getenv("LLM_KEY_REPLACEMENT_GRACE_SECONDS", "900"))),
            )
            try:
                await self._gateway.mark_replacement_grace(
                    key_id,
                    organization_id=organization_id,
                    retire_at=datetime.now(UTC) + timedelta(seconds=grace_seconds),
                )
            except Exception:
                await self._gateway.delete_key(
                    replacement.id, organization_id=organization_id
                )
                await self._ownership.release(
                    organization_id=organization_id,
                    resource_type=RESOURCE_TYPE,
                    resource_id=replacement.id,
                )
                raise
            return replacement

    async def test_key(self, *, organization_id: str, key_id: str) -> bool:
        try:
            key_id = validate_model_id(key_id)
        except ValueError as exc:
            raise ProviderSettingsError("invalid_key_id") from exc
        if not await self._ownership.owns(
            organization_id=organization_id,
            resource_type=RESOURCE_TYPE,
            resource_id=key_id,
        ):
            raise ProviderSettingsError("not_found")
        try:
            return await self._gateway.test_key(key_id, organization_id=organization_id)
        except ProviderSettingsError as exc:
            raise ProviderSettingsError(_safe_gateway_error(exc)) from exc

    async def delete_key(self, *, organization_id: str, key_id: str) -> None:
        try:
            key_id = validate_model_id(key_id)
        except ValueError as exc:
            raise ProviderSettingsError("invalid_key_id") from exc
        if not await self._ownership.owns(
            organization_id=organization_id,
            resource_type=RESOURCE_TYPE,
            resource_id=key_id,
        ):
            raise ProviderSettingsError("not_found")
        try:
            await self._gateway.delete_key(key_id, organization_id=organization_id)
        except ProviderSettingsError as exc:
            if _safe_gateway_error(exc) != "not_found":
                raise ProviderSettingsError(_safe_gateway_error(exc)) from exc
        await self._ownership.release(
            organization_id=organization_id,
            resource_type=RESOURCE_TYPE,
            resource_id=key_id,
        )
        if self._telemetry is not None:
            await self._telemetry.delete(key_id, organization_id=organization_id)

    async def selected_model_settings(
        self,
        *,
        organization_id: str,
    ) -> tuple[str, Sequence[OpenRouterModel]]:
        try:
            models = await self._catalog.list_free_models()
        except OpenRouterModelsError as exc:
            raise ProviderSettingsError("catalog_unavailable") from exc
        selected_model = await self._settings.get_selected_model(
            organization_id=organization_id
        )
        if not any(model.id == selected_model for model in models):
            selected_model = "openrouter/free"
        return selected_model, models

    async def update_selected_model(
        self, *, model_id: str, organization_id: str, updated_by: str
    ) -> str:
        try:
            valid = await self._catalog.validate_free_model(model_id)
        except OpenRouterModelsError as exc:
            raise ProviderSettingsError("catalog_unavailable") from exc
        if not valid:
            raise ProviderSettingsError("model_not_free")
        try:
            await self._gateway.update_model(model_id, organization_id=organization_id)
        except ProviderSettingsError as exc:
            raise ProviderSettingsError(_safe_gateway_error(exc)) from exc
        return await self._settings.set_selected_model(
            model_id, organization_id=organization_id, updated_by=updated_by
        )

    async def cleanup_expired_replacements(self) -> int:
        now = datetime.now(UTC)
        expired_ids: list[str] = []
        for key in await self._gateway.list_managed():
            if key.replacement_retire_at is None:
                continue
            try:
                retire_at = datetime.fromisoformat(key.replacement_retire_at)
            except ValueError as exc:
                raise ProviderSettingsError("invalid_lifecycle_metadata") from exc
            if retire_at.tzinfo is None:
                retire_at = retire_at.replace(tzinfo=UTC)
            if retire_at <= now:
                expired_ids.append(key.id)
        for key_id in expired_ids:
            try:
                await self._gateway.delete_key(
                    key_id, organization_id=key.organization_id
                )
            except ProviderSettingsError as exc:
                if _safe_gateway_error(exc) != "not_found":
                    raise ProviderSettingsError(_safe_gateway_error(exc)) from exc
            await self._ownership.release(
                organization_id=key.organization_id,
                resource_type=RESOURCE_TYPE,
                resource_id=key_id,
            )
            if self._telemetry is not None:
                await self._telemetry.delete(
                    key_id, organization_id=key.organization_id
                )
        return len(expired_ids)

    async def _test_key_material(self, key: str) -> None:
        try:
            await self._validate_key(key)
        except OpenRouterKeyTestError as exc:
            raise ProviderSettingsError(str(exc)) from exc


def _safe_gateway_error(error: Exception) -> str:
    value = str(error)
    if value in {"invalid_key", "rate_limited", "unavailable"}:
        return value
    if "not found" in value:
        return "not_found"
    return "gateway_unavailable"
