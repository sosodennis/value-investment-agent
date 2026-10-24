from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.auth.entrypoint import (
    Principal,
    require_current_user,
    require_current_user_mutation,
)
from src.llm_provider.application.wiring import get_provider_settings_service
from src.llm_provider.domain.errors import ProviderSettingsError
from src.llm_provider.domain.provider_models import ManagedProviderKey
from src.llm_provider.infrastructure.remote_client import (
    LLMProviderServiceSettingsClient,
)
from src.llm_provider.interface.contracts import (
    LlmSettingsResponse,
    LlmSettingsUpdateRequest,
    ModelOptionResponse,
    ProviderKeyCreateRequest,
    ProviderKeyResponse,
    ProviderKeyTestResponse,
)

provider_keys_router = APIRouter(
    prefix="/api/v1/llm/provider-keys", tags=["LLM settings"]
)
llm_settings_router = APIRouter(prefix="/api/v1/llm/settings", tags=["LLM settings"])


def _key_response(key: ManagedProviderKey) -> ProviderKeyResponse:
    return ProviderKeyResponse(
        id=key.id,
        label=key.label,
        suffix=key.suffix,
        fingerprint=key.fingerprint,
        created_at=key.created_at,
        status=key.status,
        last_tested_at=key.last_tested_at,
        failure_count=key.failure_count,
        cooldown_until=key.cooldown_until,
        last_error=key.last_error,
        last_used_at=key.last_used_at,
        replacement_retire_at=key.replacement_retire_at,
    )


def _raise_http_error(error: ProviderSettingsError) -> None:
    code = error.code
    if code == "not_found":
        raise HTTPException(
            status_code=404, detail="managed key was not found"
        ) from error
    if code == "invalid_key_id":
        raise HTTPException(status_code=400, detail="invalid managed key id") from error
    if code == "replacement_must_differ":
        raise HTTPException(status_code=400, detail=code) from error
    if code == "already_owned":
        raise HTTPException(
            status_code=409, detail="managed key is already owned"
        ) from error
    if code in {"invalid_key", "model_not_free", "request_rejected"}:
        raise HTTPException(status_code=400, detail=code) from error
    if code == "rate_limited":
        raise HTTPException(status_code=429, detail=code) from error
    if code == "catalog_unavailable":
        raise HTTPException(
            status_code=502, detail="OpenRouter model catalogue is unavailable"
        ) from error
    raise HTTPException(
        status_code=502, detail="LLM provider is unavailable"
    ) from error


@provider_keys_router.get("", response_model=list[ProviderKeyResponse])
async def list_provider_keys(
    principal: Principal = Depends(require_current_user),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
) -> list[ProviderKeyResponse]:
    try:
        return [
            _key_response(key)
            for key in await service.list_keys(user_id=principal.user_id)
        ]
    except ProviderSettingsError as exc:
        _raise_http_error(exc)


@provider_keys_router.post("", response_model=ProviderKeyResponse, status_code=201)
async def add_provider_key(
    request: ProviderKeyCreateRequest,
    principal: Principal = Depends(require_current_user_mutation),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
) -> ProviderKeyResponse:
    try:
        key = await service.add_key(
            user_id=principal.user_id,
            key=request.api_key.get_secret_value(),
            label=request.label,
        )
        return _key_response(key)
    except ProviderSettingsError as exc:
        _raise_http_error(exc)


@provider_keys_router.post(
    "/{key_id}/replace", response_model=ProviderKeyResponse, status_code=201
)
async def replace_provider_key(
    key_id: str,
    request: ProviderKeyCreateRequest,
    principal: Principal = Depends(require_current_user_mutation),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
) -> ProviderKeyResponse:
    try:
        key = await service.replace_key(
            user_id=principal.user_id,
            key_id=key_id,
            key=request.api_key.get_secret_value(),
            label=request.label,
        )
        return _key_response(key)
    except ProviderSettingsError as exc:
        _raise_http_error(exc)


@provider_keys_router.post("/{key_id}/test", response_model=ProviderKeyTestResponse)
async def test_provider_key(
    key_id: str,
    principal: Principal = Depends(require_current_user_mutation),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
) -> ProviderKeyTestResponse:
    try:
        await service.test_key(user_id=principal.user_id, key_id=key_id)
        return ProviderKeyTestResponse(id=key_id, passed=True, status="healthy")
    except ProviderSettingsError as exc:
        if exc.code == "not_found":
            _raise_http_error(exc)
        status = (
            exc.code if exc.code in {"invalid_key", "rate_limited"} else "unavailable"
        )
        return ProviderKeyTestResponse(id=key_id, passed=False, status=status)


@provider_keys_router.delete("/{key_id}", status_code=204)
async def delete_provider_key(
    key_id: str,
    principal: Principal = Depends(require_current_user_mutation),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
) -> None:
    try:
        await service.delete_key(user_id=principal.user_id, key_id=key_id)
    except ProviderSettingsError as exc:
        _raise_http_error(exc)


@llm_settings_router.get("", response_model=LlmSettingsResponse)
async def read_llm_settings(
    _principal: Principal = Depends(require_current_user),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
) -> LlmSettingsResponse:
    try:
        selected, models = await service.selected_model_settings(
            user_id=_principal.subject
        )
    except ProviderSettingsError as exc:
        _raise_http_error(exc)
    return LlmSettingsResponse(
        selected_model=selected,
        default_model="openrouter/free",
        models=[
            ModelOptionResponse(
                id=model.id,
                name=model.name,
                description=model.description,
                context_length=model.context_length,
            )
            for model in models
        ],
    )


@llm_settings_router.put("", response_model=LlmSettingsResponse)
async def update_llm_settings(
    request: LlmSettingsUpdateRequest,
    principal: Principal = Depends(require_current_user_mutation),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
) -> LlmSettingsResponse:
    try:
        await service.update_selected_model(
            model_id=request.selected_model, user_id=principal.user_id
        )
    except ProviderSettingsError as exc:
        _raise_http_error(exc)
    return await read_llm_settings(_principal=principal, service=service)


__all__ = ["llm_settings_router", "provider_keys_router"]
