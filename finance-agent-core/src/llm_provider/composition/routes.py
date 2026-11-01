from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from starlette.datastructures import UploadFile
from starlette.requests import Request as StarletteRequest

from src.audit.application.recording import record_best_effort
from src.audit.domain.entities import AuditOutcome
from src.auth.entrypoint import (
    Principal,
    require_current_user,
    require_current_user_mutation,
)
from src.llm_provider.application.key_import_file import (
    MAX_IMPORT_FILE_BYTES,
    MAX_MULTIPART_OVERHEAD_BYTES,
    KeyImportFileError,
    parse_key_import_file,
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
    ProviderKeyImportBatchResponse,
    ProviderKeyImportParseIssue,
    ProviderKeyImportPreviewResponse,
    ProviderKeyResponse,
    ProviderKeyTestResponse,
)

_MAX_MULTIPART_BYTES = MAX_IMPORT_FILE_BYTES + MAX_MULTIPART_OVERHEAD_BYTES
_IMPORT_FILE_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}

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
        raise HTTPException(
            status_code=400,
            detail="replacement key must differ from the current key",
        ) from error
    if code == "already_owned":
        raise HTTPException(
            status_code=409, detail="managed key is already owned"
        ) from error
    if code == "replacement_in_progress":
        raise HTTPException(
            status_code=409,
            detail="a key replacement is already in progress",
        ) from error
    if code == "idempotency_key_reused":
        raise HTTPException(status_code=409, detail=code) from error
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


async def _read_import_file(request: Request) -> tuple[str, bytes]:
    if (
        not request.headers.get("content-type", "")
        .lower()
        .startswith("multipart/form-data;")
    ):
        raise HTTPException(status_code=415, detail={"code": "multipart_required"})
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_MULTIPART_BYTES:
                raise HTTPException(
                    status_code=413, detail={"code": "request_too_large"}
                )
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail={"code": "invalid_content_length"}
            ) from exc

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_MULTIPART_BYTES:
            raise HTTPException(status_code=413, detail={"code": "request_too_large"})
        body.extend(chunk)

    consumed = False

    async def receive() -> dict[str, object]:
        nonlocal consumed
        if consumed:
            return {"type": "http.disconnect"}
        consumed = True
        return {"type": "http.request", "body": bytes(body), "more_body": False}

    form_request = StarletteRequest(request.scope, receive)
    try:
        form = await form_request.form(
            max_files=1,
            max_fields=0,
            max_part_size=MAX_IMPORT_FILE_BYTES,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail={"code": "invalid_multipart"}
        ) from exc
    try:
        if len(form) != 1:
            raise HTTPException(status_code=400, detail={"code": "file_required"})
        upload = form.get("file")
        if not isinstance(upload, UploadFile) or not isinstance(upload.filename, str):
            raise HTTPException(status_code=400, detail={"code": "file_required"})
        data = await upload.read(MAX_IMPORT_FILE_BYTES + 1)
        if len(data) > MAX_IMPORT_FILE_BYTES:
            raise HTTPException(status_code=413, detail={"code": "file_too_large"})
        return upload.filename, data
    finally:
        await form.close()


def _parse_upload(filename: str, data: bytes):
    try:
        return parse_key_import_file(filename, data)
    except KeyImportFileError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail={"code": exc.code}
        ) from exc


@provider_keys_router.get("", response_model=list[ProviderKeyResponse])
async def list_provider_keys(
    principal: Principal = Depends(require_current_user),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
) -> list[ProviderKeyResponse]:
    try:
        keys = [
            _key_response(key)
            for key in await service.list_keys(
                user_id=principal.user_id,
                organization_id=principal.organization_id,
                membership_id=principal.membership_id,
            )
        ]
        await record_best_effort(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="provider.key.listed",
            outcome=AuditOutcome.SUCCESS,
            target_type="provider",
            target_id="llm",
        )
        return keys
    except ProviderSettingsError as exc:
        _raise_http_error(exc)


@provider_keys_router.post(
    "", response_model=ProviderKeyImportBatchResponse, status_code=202
)
async def submit_provider_key(
    request: ProviderKeyCreateRequest,
    principal: Principal = Depends(require_current_user_mutation),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ProviderKeyImportBatchResponse:
    resolved_idempotency_key = (idempotency_key or "").strip() or str(uuid4())
    if not 16 <= len(resolved_idempotency_key) <= 128:
        raise HTTPException(status_code=400, detail={"code": "invalid_idempotency_key"})
    try:
        result = await service.create_key_import(
            user_id=principal.user_id,
            organization_id=principal.organization_id,
            membership_id=principal.membership_id,
            idempotency_key=resolved_idempotency_key,
            items=[
                {
                    "source_line": 1,
                    "label": request.label,
                    "api_key": request.api_key.get_secret_value(),
                }
            ],
        )
        await record_best_effort(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="provider.key.created",
            outcome=AuditOutcome.SUCCESS,
            target_type="provider",
            target_id="llm",
            payload={"item_count": 1},
        )
        return result
    except ProviderSettingsError as exc:
        _raise_http_error(exc)


@provider_keys_router.post(
    "/imports/preview",
    response_model=ProviderKeyImportPreviewResponse,
    openapi_extra=_IMPORT_FILE_OPENAPI,
)
async def preview_provider_key_import(
    request: Request,
    _principal: Principal = Depends(require_current_user_mutation),
) -> ProviderKeyImportPreviewResponse:
    filename, data = await _read_import_file(request)
    parsed = _parse_upload(filename, data)
    return ProviderKeyImportPreviewResponse(
        file_type=parsed.file_type,
        row_count=parsed.row_count,
        unique_count=parsed.unique_count,
        duplicate_count=parsed.duplicate_count,
        issues=[
            ProviderKeyImportParseIssue(
                source_line=issue.source_line,
                code=issue.code,
            )
            for issue in parsed.issues
        ],
    )


@provider_keys_router.post(
    "/imports",
    response_model=ProviderKeyImportBatchResponse,
    status_code=202,
    openapi_extra=_IMPORT_FILE_OPENAPI,
)
async def create_provider_key_import(
    request: Request,
    principal: Principal = Depends(require_current_user_mutation),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ProviderKeyImportBatchResponse:
    filename, data = await _read_import_file(request)
    parsed = _parse_upload(filename, data)
    if parsed.issues:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_rows",
                "issues": [
                    {
                        "source_line": issue.source_line,
                        "code": issue.code,
                    }
                    for issue in parsed.issues
                ],
            },
        )
    if not parsed.items:
        raise HTTPException(status_code=422, detail={"code": "no_keys_found"})
    resolved_idempotency_key = (idempotency_key or "").strip() or str(uuid4())
    if not 16 <= len(resolved_idempotency_key) <= 128:
        raise HTTPException(status_code=400, detail={"code": "invalid_idempotency_key"})
    try:
        result = await service.create_key_import(
            user_id=principal.user_id,
            organization_id=principal.organization_id,
            membership_id=principal.membership_id,
            idempotency_key=resolved_idempotency_key,
            items=[
                {
                    "source_line": item.source_line,
                    "label": item.label,
                    "api_key": item.api_key,
                }
                for item in parsed.items
            ],
        )
        await record_best_effort(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="provider.key.imported",
            outcome=AuditOutcome.SUCCESS,
            target_type="provider",
            target_id="llm",
            payload={"item_count": len(parsed.items)},
        )
        return result
    except ProviderSettingsError as exc:
        _raise_http_error(exc)


@provider_keys_router.get(
    "/imports", response_model=list[ProviderKeyImportBatchResponse]
)
async def list_provider_key_imports(
    principal: Principal = Depends(require_current_user),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
) -> list[ProviderKeyImportBatchResponse]:
    try:
        return await service.list_key_imports(
            user_id=principal.user_id,
            organization_id=principal.organization_id,
            membership_id=principal.membership_id,
        )
    except ProviderSettingsError as exc:
        _raise_http_error(exc)


@provider_keys_router.get(
    "/imports/{batch_id}", response_model=ProviderKeyImportBatchResponse
)
async def get_provider_key_import(
    batch_id: str,
    principal: Principal = Depends(require_current_user),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
) -> ProviderKeyImportBatchResponse:
    try:
        return await service.get_key_import(
            user_id=principal.user_id,
            batch_id=batch_id,
            organization_id=principal.organization_id,
            membership_id=principal.membership_id,
        )
    except ProviderSettingsError as exc:
        _raise_http_error(exc)


@provider_keys_router.post(
    "/imports/{batch_id}/retry", response_model=ProviderKeyImportBatchResponse
)
async def retry_provider_key_import(
    batch_id: str,
    principal: Principal = Depends(require_current_user_mutation),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
) -> ProviderKeyImportBatchResponse:
    try:
        result = await service.retry_key_import(
            user_id=principal.user_id,
            batch_id=batch_id,
            organization_id=principal.organization_id,
            membership_id=principal.membership_id,
        )
        await record_best_effort(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="provider.key.import_retried",
            outcome=AuditOutcome.SUCCESS,
            target_type="provider_import",
            target_id=batch_id,
        )
        return result
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
            organization_id=principal.organization_id,
            membership_id=principal.membership_id,
        )
        await record_best_effort(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="provider.key.replaced",
            outcome=AuditOutcome.SUCCESS,
            target_type="provider_key",
            target_id=key_id,
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
        passed = await service.test_key(
            user_id=principal.user_id,
            key_id=key_id,
            organization_id=principal.organization_id,
            membership_id=principal.membership_id,
        )
        await record_best_effort(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="provider.key.tested",
            outcome=AuditOutcome.SUCCESS if passed else AuditOutcome.FAILURE,
            target_type="provider_key",
            target_id=key_id,
        )
        return ProviderKeyTestResponse(
            id=key_id,
            passed=passed,
            status="healthy" if passed else "unavailable",
        )
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
        await service.delete_key(
            user_id=principal.user_id,
            key_id=key_id,
            organization_id=principal.organization_id,
            membership_id=principal.membership_id,
        )
        await record_best_effort(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="provider.key.deleted",
            outcome=AuditOutcome.SUCCESS,
            target_type="provider_key",
            target_id=key_id,
        )
    except ProviderSettingsError as exc:
        _raise_http_error(exc)


@llm_settings_router.get("", response_model=LlmSettingsResponse)
async def read_llm_settings(
    _principal: Principal = Depends(require_current_user),
    service: LLMProviderServiceSettingsClient = Depends(get_provider_settings_service),
) -> LlmSettingsResponse:
    try:
        selected, models = await service.selected_model_settings(
            user_id=_principal.subject,
            organization_id=_principal.organization_id,
            membership_id=_principal.membership_id,
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
            model_id=request.selected_model,
            user_id=principal.user_id,
            organization_id=principal.organization_id,
            membership_id=principal.membership_id,
        )
        await record_best_effort(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="provider.config.updated",
            outcome=AuditOutcome.SUCCESS,
            target_type="provider_config",
            target_id="llm",
            payload={"selected_model": request.selected_model},
        )
    except ProviderSettingsError as exc:
        _raise_http_error(exc)
    return await read_llm_settings(_principal=principal, service=service)


__all__ = ["llm_settings_router", "provider_keys_router"]
