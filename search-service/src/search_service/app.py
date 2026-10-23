from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Awaitable, Mapping
from datetime import UTC, datetime, timedelta
from typing import TypeVar, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from src.shared.internal_services import (
    INTERNAL_CONTRACT_VERSION,
    InternalAuthenticationError,
    InternalContextValidationError,
    InternalError,
    InternalErrorResponse,
    InternalReadiness,
    InternalRequestContext,
    ReadinessStatus,
    authenticate_internal_request,
)

from .contracts import (
    SEARCH_ERROR_STATUSES,
    EmptyInput,
    NewsSearchRequest,
    Operation,
    ProviderCatalog,
    ProviderCatalogResult,
    ProviderKeyAddInput,
    ProviderKeyDeleteInput,
    ProviderKeyDeleteResult,
    ProviderKeyList,
    ProviderKeyReplaceInput,
    ProviderKeyResult,
    ProviderKeySummary,
    ProviderKeyTestInput,
    ProviderKeyTestResult,
    ProviderPreference,
    SearchErrorCode,
    SearchOperationResult,
    SearchRequestBase,
    SearchResult,
    SearchSuccess,
    SettingsReadResult,
    SettingsUpdateInput,
    UserSettings,
    WebSearchRequest,
)
from .errors import SearchServiceError
from .ports import (
    ProviderCredential,
    SearchControlPlane,
    SearchProvider,
    requested_capabilities,
)
from .postgres_control_plane import PostgresSearchControlPlane
from .providers import DDGSProvider, TavilyProvider

_MAX_ATTEMPTS = 3
_MAX_CONCURRENCY = 32
_T = TypeVar("_T")
_LOGGER = logging.getLogger("search_service.execution")


def _remaining(deadline_at: datetime) -> float:
    return (deadline_at - datetime.now(UTC)).total_seconds()


async def _call_control_plane(operation: Awaitable[_T], *, deadline_at: datetime) -> _T:
    remaining = _remaining(deadline_at)
    try:
        return await asyncio.wait_for(operation, timeout=max(0, remaining))
    except TimeoutError as exc:
        raise SearchServiceError(
            SearchErrorCode.DEADLINE_EXCEEDED,
            504,
            "request deadline expired",
            True,
        ) from exc
    except SearchServiceError:
        raise
    except Exception as exc:
        raise SearchServiceError(
            SearchErrorCode.UPSTREAM_UNAVAILABLE,
            503,
            "search control plane is unavailable",
            True,
            250,
        ) from exc


async def _test_provider_key(
    provider: SearchProvider, api_key: str, *, deadline_at: datetime
) -> bool:
    try:
        return await asyncio.wait_for(
            provider.test_key(api_key, deadline_at=deadline_at),
            timeout=max(0, _remaining(deadline_at)),
        )
    except TimeoutError as exc:
        raise SearchServiceError(
            SearchErrorCode.DEADLINE_EXCEEDED,
            504,
            "request deadline expired",
            True,
        ) from exc
    except SearchServiceError:
        raise
    except Exception as exc:
        raise SearchServiceError(
            SearchErrorCode.UPSTREAM_UNAVAILABLE,
            503,
            "provider key test is unavailable",
            True,
            250,
        ) from exc


def _fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:24]


def _safe_suffix(api_key: str) -> str:
    return api_key[-4:].rjust(4, "*")


def _correlation_id(raw: object) -> str:
    if isinstance(raw, dict):
        context = raw.get("context")
        if isinstance(context, dict):
            value = context.get("correlation_id")
            if isinstance(value, str) and 0 < len(value) <= 128:
                return value
    return "unknown"


def create_app(
    *,
    providers: Mapping[str, SearchProvider],
    control_plane: SearchControlPlane,
    token: str | None = None,
) -> FastAPI:
    service_token = (
        token if token is not None else os.getenv("SEARCH_SERVICE_TOKEN", "")
    )
    application = FastAPI(
        title="Private Search Service",
        version="search.v1",
    )
    provider_slots = asyncio.Semaphore(_MAX_CONCURRENCY)

    def response_error(
        request: Request,
        *,
        correlation_id: str,
        code: str,
        message: str,
        status: int,
        retryable: bool = False,
        retry_after_ms: int | None = None,
    ) -> JSONResponse:
        if correlation_id == "unknown":
            correlation_id = getattr(request.state, "correlation_id", "unknown")
        body = InternalErrorResponse(
            correlation_id=correlation_id,
            contract_version=INTERNAL_CONTRACT_VERSION,
            error=InternalError(
                code=code,
                message=message,
                retryable=retryable,
                retry_after_ms=retry_after_ms,
            ),
        )
        frozen_status = SEARCH_ERROR_STATUSES.get(code, status)
        return JSONResponse(
            status_code=frozen_status, content=body.model_dump(mode="json")
        )

    def success(context: InternalRequestContext, result: BaseModel) -> JSONResponse:
        return JSONResponse(
            content={
                "correlation_id": context.correlation_id,
                "contract_version": INTERNAL_CONTRACT_VERSION,
                "result": result.model_dump(mode="json"),
            }
        )

    def authorize(request: Request, raw: object) -> InternalRequestContext:
        raw_context = raw.get("context", {}) if isinstance(raw, dict) else {}
        if not isinstance(raw_context, dict):
            raw_context = {}
        return authenticate_internal_request(
            request.headers.get("Authorization"),
            expected_token=service_token,
            raw_context=raw_context,
        )

    async def read_json(request: Request) -> object:
        try:
            raw = await request.json()
            request.state.correlation_id = _correlation_id(raw)
            return raw
        except Exception as exc:
            raise SearchServiceError(
                SearchErrorCode.INVALID_REQUEST, 400, "request body is invalid"
            ) from exc

    def read_input(raw: object, model: type[SearchRequestBase]) -> SearchRequestBase:
        if (
            not isinstance(raw, dict)
            or set(raw) != {"context", "input"}
            or not isinstance(raw.get("input"), dict)
        ):
            raise SearchServiceError(
                SearchErrorCode.INVALID_REQUEST, 400, "operation input is invalid"
            )
        return model.model_validate(raw["input"])

    async def run_search(request: Request, operation: Operation) -> JSONResponse:
        correlation_id = "unknown"
        try:
            raw = await read_json(request)
            correlation_id = _correlation_id(raw)
            context = authorize(request, raw)
            correlation_id = context.correlation_id
            model: type[SearchRequestBase] = (
                WebSearchRequest if operation is Operation.WEB else NewsSearchRequest
            )
            payload = read_input(raw, model)
            operation_deadline = min(
                context.deadline_at,
                datetime.now(UTC) + timedelta(seconds=payload.timeout_seconds),
            )
            requested = requested_capabilities(payload)
            credentials = await _call_control_plane(
                control_plane.credentials_for(subject_id=context.principal.subject_id),
                deadline_at=operation_deadline,
            )
            eligible: list[tuple[int, str, SearchProvider, str]] = []
            for credential in credentials:
                provider = providers.get(credential.provider)
                if provider is None or not credential.enabled:
                    continue
                if provider.capabilities.key_required and not credential.api_key:
                    continue
                if operation not in provider.capabilities.operations:
                    continue
                if not requested.issubset(provider.capabilities.optional_fields):
                    continue
                eligible.append(
                    (
                        credential.priority,
                        credential.provider,
                        provider,
                        credential.api_key,
                    )
                )
            if not eligible:
                raise SearchServiceError(
                    SearchErrorCode.UNSUPPORTED_CAPABILITY,
                    422,
                    "no enabled provider supports this operation and its options",
                )

            last_provider_error: SearchServiceError | None = None
            for _priority, _name, provider, api_key in sorted(eligible)[:_MAX_ATTEMPTS]:
                remaining = _remaining(operation_deadline)
                if remaining <= 0:
                    raise SearchServiceError(
                        SearchErrorCode.DEADLINE_EXCEEDED,
                        504,
                        "request deadline expired",
                        True,
                    )
                acquired = False
                try:
                    await asyncio.wait_for(provider_slots.acquire(), timeout=remaining)
                    acquired = True
                    raw_results = await asyncio.wait_for(
                        provider.search(
                            operation=operation,
                            request=payload,
                            api_key=api_key,
                            deadline_at=operation_deadline,
                        ),
                        timeout=_remaining(operation_deadline),
                    )
                    results = tuple(
                        SearchResult.model_validate(item) for item in raw_results
                    )
                    result = SearchOperationResult(
                        operation=operation,
                        results=results[: payload.result_limit],
                    )
                    response = SearchSuccess(
                        correlation_id=context.correlation_id,
                        contract_version="internal.v1",
                        result=result,
                    )
                    _LOGGER.info(
                        "search_provider_succeeded",
                        extra={
                            "correlation_id": context.correlation_id,
                            "provider": provider.name,
                            "operation": operation.value,
                            "result_count": len(results),
                        },
                    )
                    return JSONResponse(content=response.model_dump(mode="json"))
                except TimeoutError as exc:
                    raise SearchServiceError(
                        SearchErrorCode.DEADLINE_EXCEEDED,
                        504,
                        "request deadline expired",
                        True,
                    ) from exc
                except ValidationError:
                    _LOGGER.warning(
                        "search_provider_failed",
                        extra={
                            "correlation_id": context.correlation_id,
                            "provider": provider.name,
                            "operation": operation.value,
                            "error_code": str(SearchErrorCode.UPSTREAM_MALFORMED),
                        },
                    )
                    last_provider_error = SearchServiceError(
                        SearchErrorCode.UPSTREAM_MALFORMED,
                        502,
                        "provider response could not be normalized",
                    )
                except SearchServiceError as exc:
                    _LOGGER.warning(
                        "search_provider_failed",
                        extra={
                            "correlation_id": context.correlation_id,
                            "provider": provider.name,
                            "operation": operation.value,
                            "error_code": str(exc.code),
                        },
                    )
                    if exc.code == SearchErrorCode.RATE_LIMITED:
                        record_failure = getattr(control_plane, "record_failure", None)
                        if record_failure is not None:
                            await _call_control_plane(
                                record_failure(
                                    subject_id=context.principal.subject_id,
                                    provider=provider.name,
                                ),
                                deadline_at=operation_deadline,
                            )
                    if exc.code in {
                        SearchErrorCode.AUTHENTICATION_FAILED,
                        SearchErrorCode.DEADLINE_EXCEEDED,
                        SearchErrorCode.RATE_LIMITED,
                        SearchErrorCode.UPSTREAM_MALFORMED,
                    }:
                        last_provider_error = exc
                except Exception:
                    _LOGGER.warning(
                        "search_provider_failed",
                        extra={
                            "correlation_id": context.correlation_id,
                            "provider": provider.name,
                            "operation": operation.value,
                            "error_code": str(SearchErrorCode.UPSTREAM_UNAVAILABLE),
                        },
                    )
                    continue
                finally:
                    if acquired:
                        provider_slots.release()
            if last_provider_error is not None:
                raise last_provider_error
            raise SearchServiceError(
                SearchErrorCode.UPSTREAM_UNAVAILABLE,
                503,
                "search providers are unavailable",
                True,
                250,
            )
        except InternalAuthenticationError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=str(exc),
                status=401,
            )
        except InternalContextValidationError:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=SearchErrorCode.INVALID_REQUEST,
                message="request context is invalid",
                status=400,
            )
        except ValidationError:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=SearchErrorCode.INVALID_REQUEST,
                message="operation input failed validation",
                status=400,
            )
        except SearchServiceError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=exc.message,
                status=exc.status_code,
                retryable=exc.retryable,
                retry_after_ms=exc.retry_after_ms,
            )
        except Exception:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=SearchErrorCode.UPSTREAM_UNAVAILABLE,
                message="search service is unavailable",
                status=503,
                retryable=True,
                retry_after_ms=250,
            )

    async def run_context_operation(
        request: Request,
    ) -> tuple[InternalRequestContext, object]:
        raw = await read_json(request)
        context = authorize(request, raw)
        if (
            not isinstance(raw, dict)
            or set(raw) != {"context", "input"}
            or not isinstance(raw.get("input"), dict)
        ):
            raise SearchServiceError(
                SearchErrorCode.INVALID_REQUEST, 400, "operation input is invalid"
            )
        if _remaining(context.deadline_at) <= 0:
            raise SearchServiceError(
                SearchErrorCode.DEADLINE_EXCEEDED, 504, "request deadline expired", True
            )
        return context, raw["input"]

    @application.exception_handler(SearchServiceError)
    async def handle_service_error(
        request: Request, exc: SearchServiceError
    ) -> JSONResponse:
        return response_error(
            request,
            correlation_id="unknown",
            code=exc.code,
            message=exc.message,
            status=exc.status_code,
            retryable=exc.retryable,
            retry_after_ms=exc.retry_after_ms,
        )

    @application.get("/livez")
    async def livez() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz")
    async def readyz() -> JSONResponse:
        ready = bool(service_token and providers) and not isinstance(
            control_plane, _UnavailableControlPlane
        )
        check_control_plane = getattr(control_plane, "is_ready", None)
        if ready and check_control_plane is not None:
            try:
                ready = await asyncio.wait_for(check_control_plane(), timeout=2.0)
            except Exception:
                ready = False
        body = InternalReadiness(
            status=ReadinessStatus.READY if ready else ReadinessStatus.NOT_READY,
            contract_version=INTERNAL_CONTRACT_VERSION,
        )
        return JSONResponse(
            status_code=200 if ready else 503,
            content=body.model_dump(mode="json"),
        )

    @application.get("/contract")
    async def contract() -> dict[str, object]:
        return {
            "contract_version": INTERNAL_CONTRACT_VERSION,
            "schema_version": "search.v1",
            "operations": [Operation.WEB.value, Operation.NEWS.value],
        }

    @application.post("/v1/search/web")
    async def web_search(request: Request) -> JSONResponse:
        return await run_search(request, Operation.WEB)

    @application.post("/v1/search/news")
    async def news_search(request: Request) -> JSONResponse:
        return await run_search(request, Operation.NEWS)

    @application.post("/v1/providers/catalog")
    async def provider_catalog(request: Request) -> JSONResponse:
        correlation_id = "unknown"
        try:
            context, raw_input = await run_context_operation(request)
            correlation_id = context.correlation_id
            EmptyInput.model_validate(raw_input)
            catalog = ProviderCatalog(
                providers=tuple(
                    provider.capabilities.model_copy(update={"provider": name})
                    for name, provider in sorted(providers.items())
                )
            )
            return success(context, ProviderCatalogResult(catalog=catalog))
        except InternalAuthenticationError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=str(exc),
                status=401,
            )
        except (InternalContextValidationError, ValidationError):
            return response_error(
                request,
                correlation_id=correlation_id,
                code=SearchErrorCode.INVALID_REQUEST,
                message="provider catalog request is invalid",
                status=400,
            )
        except SearchServiceError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=exc.message,
                status=exc.status_code,
                retryable=exc.retryable,
                retry_after_ms=exc.retry_after_ms,
            )

    @application.post("/v1/settings/read")
    async def settings_read(request: Request) -> JSONResponse:
        correlation_id = "unknown"
        try:
            context, raw_input = await run_context_operation(request)
            correlation_id = context.correlation_id
            EmptyInput.model_validate(raw_input)
            settings = await _call_control_plane(
                control_plane.get_settings(subject_id=context.principal.subject_id),
                deadline_at=context.deadline_at,
            )
            return success(context, SettingsReadResult(settings=settings))
        except InternalAuthenticationError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=str(exc),
                status=401,
            )
        except (InternalContextValidationError, ValidationError):
            return response_error(
                request,
                correlation_id=correlation_id,
                code=SearchErrorCode.INVALID_REQUEST,
                message="request context is invalid",
                status=400,
            )
        except SearchServiceError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=exc.message,
                status=exc.status_code,
                retryable=exc.retryable,
                retry_after_ms=exc.retry_after_ms,
            )

    @application.post("/v1/settings/update")
    async def settings_update(request: Request) -> JSONResponse:
        correlation_id = "unknown"
        try:
            context, raw_input = await run_context_operation(request)
            correlation_id = context.correlation_id
            payload = SettingsUpdateInput.model_validate(raw_input)
            names = [item.provider for item in payload.providers]
            priorities = [item.priority for item in payload.providers]
            if len(set(names)) != len(names) or len(set(priorities)) != len(priorities):
                raise SearchServiceError(
                    SearchErrorCode.INVALID_REQUEST,
                    400,
                    "provider settings must have unique providers and priorities",
                )
            if any(name not in providers for name in names):
                raise SearchServiceError(
                    SearchErrorCode.INVALID_REQUEST,
                    400,
                    "provider settings contain an unknown provider",
                )
            result = await _call_control_plane(
                control_plane.replace_settings(
                    subject_id=context.principal.subject_id,
                    providers=payload.providers,
                ),
                deadline_at=context.deadline_at,
            )
            return success(context, SettingsReadResult(settings=result))
        except InternalAuthenticationError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=str(exc),
                status=401,
            )
        except (InternalContextValidationError, ValidationError):
            return response_error(
                request,
                correlation_id=correlation_id,
                code=SearchErrorCode.INVALID_REQUEST,
                message="settings update is invalid",
                status=400,
            )
        except SearchServiceError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=exc.message,
                status=exc.status_code,
                retryable=exc.retryable,
                retry_after_ms=exc.retry_after_ms,
            )

    @application.post("/v1/provider-keys/test")
    async def provider_key_test(request: Request) -> JSONResponse:
        correlation_id = "unknown"
        try:
            context, raw_input = await run_context_operation(request)
            correlation_id = context.correlation_id
            payload = ProviderKeyTestInput.model_validate(raw_input)
            provider = providers.get(payload.provider)
            if provider is None:
                raise SearchServiceError(
                    SearchErrorCode.UNSUPPORTED_CAPABILITY,
                    422,
                    "provider is not configured",
                )
            key = payload.api_key.get_secret_value()
            valid = await _test_provider_key(
                provider, key, deadline_at=context.deadline_at
            )
            result = ProviderKeyTestResult(
                provider=payload.provider,
                valid=valid,
                status="valid" if valid else "invalid",
            )
            return success(context, result)
        except InternalAuthenticationError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=str(exc),
                status=401,
            )
        except (InternalContextValidationError, ValidationError):
            return response_error(
                request,
                correlation_id=correlation_id,
                code=SearchErrorCode.INVALID_REQUEST,
                message="key test request is invalid",
                status=400,
            )
        except TimeoutError:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=SearchErrorCode.DEADLINE_EXCEEDED,
                message="request deadline expired",
                status=504,
                retryable=True,
            )
        except SearchServiceError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=exc.message,
                status=exc.status_code,
                retryable=exc.retryable,
                retry_after_ms=exc.retry_after_ms,
            )

    @application.post("/v1/provider-keys/add")
    async def provider_key_add(request: Request) -> JSONResponse:
        return await mutate_provider_key(request, replace=False)

    @application.post("/v1/provider-keys/replace")
    async def provider_key_replace(request: Request) -> JSONResponse:
        return await mutate_provider_key(request, replace=True)

    async def mutate_provider_key(request: Request, *, replace: bool) -> JSONResponse:
        correlation_id = "unknown"
        try:
            context, raw_input = await run_context_operation(request)
            correlation_id = context.correlation_id
            payload = (
                ProviderKeyReplaceInput.model_validate(raw_input)
                if replace
                else ProviderKeyAddInput.model_validate(raw_input)
            )
            provider = providers.get(payload.provider)
            if provider is None:
                raise SearchServiceError(
                    SearchErrorCode.UNSUPPORTED_CAPABILITY,
                    422,
                    "provider is not configured",
                )
            key = payload.api_key.get_secret_value()
            valid = await _test_provider_key(
                provider, key, deadline_at=context.deadline_at
            )
            if not valid:
                raise SearchServiceError(
                    SearchErrorCode.AUTHENTICATION_FAILED,
                    422,
                    "provider key test failed",
                )
            if isinstance(payload, ProviderKeyReplaceInput):
                key_operation = control_plane.replace_tested_key(
                    subject_id=context.principal.subject_id,
                    provider=payload.provider,
                    api_key=key,
                    label=payload.label,
                    suffix=_safe_suffix(key),
                    fingerprint=_fingerprint(key),
                    key_id=payload.key_id,
                )
            else:
                key_operation = control_plane.add_tested_key(
                    subject_id=context.principal.subject_id,
                    provider=payload.provider,
                    api_key=key,
                    label=payload.label,
                    suffix=_safe_suffix(key),
                    fingerprint=_fingerprint(key),
                )
            summary = await _call_control_plane(
                key_operation, deadline_at=context.deadline_at
            )
            return success(
                context,
                ProviderKeyResult(
                    id=summary.id,
                    provider=payload.provider,
                    tested=True,
                    active=True,
                    suffix=summary.suffix,
                    fingerprint=summary.fingerprint,
                ),
            )
        except InternalAuthenticationError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=str(exc),
                status=401,
            )
        except (InternalContextValidationError, ValidationError):
            return response_error(
                request,
                correlation_id=correlation_id,
                code=SearchErrorCode.INVALID_REQUEST,
                message="key mutation request is invalid",
                status=400,
            )
        except TimeoutError:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=SearchErrorCode.DEADLINE_EXCEEDED,
                message="request deadline expired",
                status=504,
                retryable=True,
            )
        except SearchServiceError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=exc.message,
                status=exc.status_code,
                retryable=exc.retryable,
                retry_after_ms=exc.retry_after_ms,
            )

    @application.post("/v1/provider-keys/delete")
    async def provider_key_delete(request: Request) -> JSONResponse:
        correlation_id = "unknown"
        try:
            context, raw_input = await run_context_operation(request)
            correlation_id = context.correlation_id
            payload = ProviderKeyDeleteInput.model_validate(raw_input)
            await _call_control_plane(
                control_plane.delete_key(
                    subject_id=context.principal.subject_id, key_id=payload.key_id
                ),
                deadline_at=context.deadline_at,
            )
            return success(context, ProviderKeyDeleteResult(deleted=True))
        except InternalAuthenticationError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=str(exc),
                status=401,
            )
        except (InternalContextValidationError, ValidationError):
            return response_error(
                request,
                correlation_id=correlation_id,
                code=SearchErrorCode.INVALID_REQUEST,
                message="key delete request is invalid",
                status=400,
            )
        except SearchServiceError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=exc.message,
                status=exc.status_code,
                retryable=exc.retryable,
                retry_after_ms=exc.retry_after_ms,
            )

    @application.post("/v1/provider-keys/list")
    async def provider_key_list(request: Request) -> JSONResponse:
        correlation_id = "unknown"
        try:
            context, raw_input = await run_context_operation(request)
            correlation_id = context.correlation_id
            EmptyInput.model_validate(raw_input)
            result = ProviderKeyList(
                providers=await _call_control_plane(
                    control_plane.list_keys(subject_id=context.principal.subject_id),
                    deadline_at=context.deadline_at,
                )
            )
            return success(context, result)
        except InternalAuthenticationError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=str(exc),
                status=401,
            )
        except (InternalContextValidationError, ValidationError):
            return response_error(
                request,
                correlation_id=correlation_id,
                code=SearchErrorCode.INVALID_REQUEST,
                message="request context is invalid",
                status=400,
            )
        except SearchServiceError as exc:
            return response_error(
                request,
                correlation_id=correlation_id,
                code=exc.code,
                message=exc.message,
                status=exc.status_code,
                retryable=exc.retryable,
                retry_after_ms=exc.retry_after_ms,
            )

    return application


class _UnavailableControlPlane:
    async def credentials_for(
        self, *, subject_id: str
    ) -> tuple[ProviderCredential, ...]:
        raise RuntimeError("search control plane is not configured")

    async def add_tested_key(
        self,
        *,
        subject_id: str,
        provider: str,
        api_key: str,
        label: str,
        suffix: str,
        fingerprint: str,
    ) -> ProviderKeySummary:
        raise RuntimeError("search control plane is not configured")

    async def replace_tested_key(
        self,
        *,
        subject_id: str,
        provider: str,
        api_key: str,
        label: str,
        suffix: str,
        fingerprint: str,
        key_id: str,
    ) -> ProviderKeySummary:
        raise RuntimeError("search control plane is not configured")

    async def list_keys(self, *, subject_id: str) -> tuple[ProviderKeySummary, ...]:
        raise RuntimeError("search control plane is not configured")

    async def delete_key(self, *, subject_id: str, key_id: str) -> None:
        raise RuntimeError("search control plane is not configured")

    async def get_settings(self, *, subject_id: str) -> UserSettings:
        raise RuntimeError("search control plane is not configured")

    async def replace_settings(
        self, *, subject_id: str, providers: tuple[ProviderPreference, ...]
    ) -> UserSettings:
        raise RuntimeError("search control plane is not configured")


_default_providers: dict[str, SearchProvider] = {"ddgs": DDGSProvider()}
if os.getenv("TAVILY_API_ENABLED", "1").lower() not in {"0", "false", "no"}:
    _default_providers["tavily"] = TavilyProvider()

_database_url = os.getenv("SEARCH_CONTROL_DATABASE_URL", "")
_encryption_key = os.getenv("SEARCH_PROVIDER_ENCRYPTION_KEY", "")
_default_control_plane = cast(
    SearchControlPlane,
    PostgresSearchControlPlane(_database_url, _encryption_key)
    if _database_url and _encryption_key
    else _UnavailableControlPlane(),
)
app = create_app(providers=_default_providers, control_plane=_default_control_plane)
