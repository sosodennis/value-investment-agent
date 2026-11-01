from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException

from src.audit.application.recording import record_best_effort
from src.audit.domain.entities import AuditOutcome
from src.auth.entrypoint import (
    Principal,
    require_current_user,
    require_current_user_mutation,
)
from src.search_settings.domain import (
    ProviderKeyCreateRequest,
    ProviderKeyEnabledRequest,
    ProviderKeyReplaceRequest,
    ProviderKeyResponse,
    ProviderPreferencesRequest,
    SearchSettingsResponse,
)
from src.search_settings.infrastructure.client import (
    SearchServiceClient,
    SearchServiceError,
)

search_settings_router = APIRouter(
    prefix="/api/v1/search/settings", tags=["Search settings"]
)


@lru_cache
def get_search_service() -> SearchServiceClient:
    return SearchServiceClient()


async def close_search_service() -> None:
    if get_search_service.cache_info().currsize == 0:
        return
    service = get_search_service()
    get_search_service.cache_clear()
    await service.aclose()


def _raise(error: SearchServiceError) -> None:
    status = (
        error.status if error.status in {400, 401, 404, 409, 422, 429, 503} else 502
    )
    raise HTTPException(status_code=status, detail=error.code) from error


@search_settings_router.get("", response_model=SearchSettingsResponse)
async def read_search_settings(
    principal: Principal = Depends(require_current_user),
    service: SearchServiceClient = Depends(get_search_service),
) -> SearchSettingsResponse:
    try:
        catalog, settings = await service.read(principal=principal.user_id)
        return SearchSettingsResponse(providers=catalog, settings=settings)
    except SearchServiceError as exc:
        _raise(exc)


@search_settings_router.put("", response_model=SearchSettingsResponse)
async def update_search_settings(
    request: ProviderPreferencesRequest,
    principal: Principal = Depends(require_current_user_mutation),
    service: SearchServiceClient = Depends(get_search_service),
) -> SearchSettingsResponse:
    try:
        catalog = await service.catalog(principal=principal.user_id)
        settings = await service.update(
            principal=principal.user_id, providers=request.providers
        )
        await record_best_effort(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="provider.config.updated",
            outcome=AuditOutcome.SUCCESS,
            target_type="provider_config",
            target_id="search",
            payload={"provider_count": len(request.providers)},
        )
        return SearchSettingsResponse(providers=catalog, settings=settings)
    except SearchServiceError as exc:
        _raise(exc)


@search_settings_router.post(
    "/keys", response_model=ProviderKeyResponse, status_code=201
)
async def add_search_key(
    request: ProviderKeyCreateRequest,
    principal: Principal = Depends(require_current_user_mutation),
    service: SearchServiceClient = Depends(get_search_service),
) -> ProviderKeyResponse:
    try:
        result = await service.add_key(
            principal=principal.user_id,
            provider=request.provider,
            api_key=request.api_key.get_secret_value(),
            label=request.label,
        )
        await record_best_effort(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="provider.key.created",
            outcome=AuditOutcome.SUCCESS,
            target_type="provider",
            target_id="search",
            payload={"provider": request.provider},
        )
        return ProviderKeyResponse(**result.model_dump())
    except SearchServiceError as exc:
        _raise(exc)


@search_settings_router.put(
    "/keys", response_model=ProviderKeyResponse, status_code=201
)
async def replace_search_key(
    request: ProviderKeyReplaceRequest,
    principal: Principal = Depends(require_current_user_mutation),
    service: SearchServiceClient = Depends(get_search_service),
) -> ProviderKeyResponse:
    try:
        result = await service.replace_key(
            principal=principal.user_id,
            key_id=request.key_id,
            provider=request.provider,
            api_key=request.api_key.get_secret_value(),
            label=request.label,
        )
        await record_best_effort(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="provider.key.replaced",
            outcome=AuditOutcome.SUCCESS,
            target_type="provider_key",
            target_id=request.key_id,
            payload={"provider": request.provider},
        )
        return ProviderKeyResponse(**result.model_dump())
    except SearchServiceError as exc:
        _raise(exc)


@search_settings_router.delete("/keys/{key_id}", status_code=204)
async def delete_search_key(
    key_id: str,
    principal: Principal = Depends(require_current_user_mutation),
    service: SearchServiceClient = Depends(get_search_service),
) -> None:
    try:
        await service.delete_key(principal=principal.user_id, key_id=key_id)
        await record_best_effort(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="provider.key.deleted",
            outcome=AuditOutcome.SUCCESS,
            target_type="provider_key",
            target_id=key_id,
        )
    except SearchServiceError as exc:
        _raise(exc)


@search_settings_router.patch("/keys/{key_id}", response_model=ProviderKeyResponse)
async def set_search_key_enabled(
    key_id: str,
    request: ProviderKeyEnabledRequest,
    principal: Principal = Depends(require_current_user_mutation),
    service: SearchServiceClient = Depends(get_search_service),
) -> ProviderKeyResponse:
    try:
        result = await service.set_key_enabled(
            principal=principal.user_id, key_id=key_id, enabled=request.enabled
        )
        await record_best_effort(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="provider.key.enabled"
            if request.enabled
            else "provider.key.disabled",
            outcome=AuditOutcome.SUCCESS,
            target_type="provider_key",
            target_id=key_id,
        )
        return ProviderKeyResponse(**result.model_dump())
    except SearchServiceError as exc:
        _raise(exc)
