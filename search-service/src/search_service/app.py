from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeVar, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from src.shared.internal_services import (
    INTERNAL_CONTEXT_ISSUER,
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
    ProviderKeySetEnabledInput,
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
_LEASE_SECONDS = 30
_MAX_BACKOFF_SECONDS = 0.25
_T = TypeVar("_T")
_LOGGER = logging.getLogger("search_service.execution")


@dataclass(frozen=True)
class _CredentialView:
    """Runtime view of a credential, tolerant of the pre-pool contract."""

    provider: str
    api_key: str
    key_id: str | None
    enabled: bool
    provider_priority: int
    key_priority: int
    status: str
    cooldown_until: datetime | None


def _value(item: object, name: str, default: object = None) -> object:
    return getattr(item, name, default)


def _int_value(item: object, name: str, default: int) -> int:
    value = _value(item, name, default)
    return value if isinstance(value, int) else default


def _secret_value(raw: object) -> str:
    getter = getattr(raw, "get_secret_value", None)
    if callable(getter):
        value = getter()
        return value if isinstance(value, str) else ""
    return raw if isinstance(raw, str) else ""


def _credential_view(item: object) -> _CredentialView:
    provider = _value(item, "provider", "")
    provider_name = provider if isinstance(provider, str) else ""
    key_id = _value(item, "key_id", None)
    provider_priority = _int_value(item, "provider_priority", -1)
    if provider_priority < 0:
        provider_priority = _int_value(item, "priority", 0)
    key_priority = _int_value(item, "key_priority", -1)
    if key_priority < 0:
        key_priority = _int_value(item, "priority", 0)
    cooldown_until = _value(item, "cooldown_until", None)
    return _CredentialView(
        provider=provider_name,
        api_key=_secret_value(_value(item, "api_key", "")),
        key_id=key_id if isinstance(key_id, str) else None,
        enabled=bool(_value(item, "enabled", True)),
        provider_priority=provider_priority,
        key_priority=key_priority,
        status=str(_value(item, "status", "active")),
        cooldown_until=cooldown_until if isinstance(cooldown_until, datetime) else None,
    )


def _eligible_credential(credential: _CredentialView, *, now: datetime) -> bool:
    if not credential.enabled or credential.status in {"disabled", "invalid"}:
        return False
    return credential.cooldown_until is None or credential.cooldown_until <= now


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


async def _claim_credential(
    control_plane: SearchControlPlane,
    *,
    organization_id: str,
    provider: str,
    deadline_at: datetime,
) -> object | None:
    return await _call_control_plane(
        control_plane.claim_credential(
            organization_id=organization_id,
            provider=provider,
            lease_seconds=_LEASE_SECONDS,
        ),
        deadline_at=deadline_at,
    )


async def _release_credential(
    control_plane: SearchControlPlane,
    *,
    organization_id: str,
    credential: _CredentialView,
    succeeded: bool,
    deadline_at: datetime,
) -> None:
    if credential.key_id is None:
        return
    if _remaining(deadline_at) <= 0:
        return
    await _call_control_plane(
        control_plane.release_credential(
            organization_id=organization_id,
            key_id=credential.key_id,
            succeeded=succeeded,
        ),
        deadline_at=deadline_at,
    )


async def _record_credential_failure(
    control_plane: SearchControlPlane,
    *,
    organization_id: str,
    credential: _CredentialView,
    error: SearchServiceError,
    deadline_at: datetime,
) -> None:
    """Persist key health without making telemetry a second retry loop."""

    cooldown_seconds = max(1, min(60, (error.retry_after_ms or 30) // 1000))
    if error.retry_after_ms is not None:
        cooldown_seconds = max(1, min(60, (error.retry_after_ms + 999) // 1000))
    status = (
        "invalid" if error.code == SearchErrorCode.AUTHENTICATION_FAILED else "cooldown"
    )
    if (
        error.code
        in {
            SearchErrorCode.DEADLINE_EXCEEDED,
            SearchErrorCode.INVALID_REQUEST,
            SearchErrorCode.UNSUPPORTED_CAPABILITY,
        }
        or _remaining(deadline_at) <= 0
    ):
        return
    try:
        provider_scoped = error.code in {
            SearchErrorCode.UPSTREAM_UNAVAILABLE,
            SearchErrorCode.UPSTREAM_MALFORMED,
        }
        if provider_scoped:
            operation = control_plane.record_provider_failure(
                organization_id=organization_id,
                provider=credential.provider,
                cooldown_seconds=cooldown_seconds,
            )
        elif credential.key_id is not None:
            operation = control_plane.record_key_failure(
                organization_id=organization_id,
                key_id=credential.key_id,
                status=status,
                cooldown_seconds=cooldown_seconds,
            )
        else:
            operation = control_plane.record_provider_failure(
                organization_id=organization_id,
                provider=credential.provider,
                cooldown_seconds=cooldown_seconds,
            )
        await _call_control_plane(operation, deadline_at=deadline_at)
    except SearchServiceError as exc:
        if exc.code == SearchErrorCode.DEADLINE_EXCEEDED:
            raise
        _LOGGER.warning(
            "search_credential_health_update_failed",
            extra={"provider": credential.provider, "error_code": str(exc.code)},
        )


def _backoff_seconds(error: SearchServiceError, attempt: int) -> float:
    retry_after: float = (error.retry_after_ms or 0) / 1000
    exponential: float = min(_MAX_BACKOFF_SECONDS, 0.02 * (2 ** max(0, attempt - 1)))
    base: float = min(_MAX_BACKOFF_SECONDS, max(retry_after, exponential))
    jitter: float = random.uniform(0, min(0.02, base))
    return min(_MAX_BACKOFF_SECONDS, base + jitter)


async def _pause_before_retry(
    error: SearchServiceError, *, attempt: int, deadline_at: datetime
) -> None:
    delay = _backoff_seconds(error, attempt)
    remaining = _remaining(deadline_at)
    if remaining <= 0:
        raise SearchServiceError(
            SearchErrorCode.DEADLINE_EXCEEDED,
            504,
            "request deadline expired",
            True,
        )
    await asyncio.sleep(min(delay, remaining))


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
        context = authenticate_internal_request(
            request.headers.get("Authorization"),
            expected_token=service_token,
            raw_context=raw_context,
            expected_audience="search-service",
            expected_issuer=INTERNAL_CONTEXT_ISSUER,
            organization_header=request.headers.get("X-Organization-ID"),
        )
        if context.principal.organization_id in {
            None,
            "unscoped",
        } or context.principal.membership_id in {None, "unscoped"}:
            raise InternalContextValidationError()
        return context

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
                control_plane.credentials_for(
                    organization_id=context.principal.organization_id
                ),
                deadline_at=operation_deadline,
            )
            now = datetime.now(UTC)
            grouped: dict[str, list[_CredentialView]] = {}
            for raw_credential in credentials:
                credential = _credential_view(raw_credential)
                if _eligible_credential(credential, now=now):
                    grouped.setdefault(credential.provider, []).append(credential)

            eligible_providers: list[tuple[int, str, SearchProvider]] = []
            for name, provider in providers.items():
                if operation not in provider.capabilities.operations:
                    continue
                if not requested.issubset(provider.capabilities.optional_fields):
                    continue
                keys = grouped.get(name, [])
                if provider.capabilities.key_required:
                    keys = [item for item in keys if item.api_key]
                if provider.capabilities.key_required and not keys:
                    continue
                provider_priority = min(
                    (item.provider_priority for item in keys), default=10_000
                )
                eligible_providers.append((provider_priority, name, provider))
            if not eligible_providers:
                raise SearchServiceError(
                    SearchErrorCode.UNSUPPORTED_CAPABILITY,
                    422,
                    "no enabled provider supports this operation and its options",
                )

            attempted_keys: set[str] = set()
            total_attempts = 0
            last_error: SearchServiceError | None = None
            for _priority, provider_name, provider in sorted(eligible_providers):
                provider_keys = sorted(
                    grouped.get(provider_name, []),
                    key=lambda item: (item.key_priority, item.key_id or item.api_key),
                )
                if provider.capabilities.key_required:
                    provider_keys = [item for item in provider_keys if item.api_key]
                # Keyless providers (for example DDGS) get one synthetic key.
                if not provider_keys and not provider.capabilities.key_required:
                    provider_keys = [
                        _CredentialView(
                            provider=provider_name,
                            api_key="",
                            key_id=None,
                            enabled=True,
                            provider_priority=_priority,
                            key_priority=0,
                            status="active",
                            cooldown_until=None,
                        )
                    ]
                while total_attempts < _MAX_ATTEMPTS:
                    remaining = _remaining(operation_deadline)
                    if remaining <= 0:
                        raise SearchServiceError(
                            SearchErrorCode.DEADLINE_EXCEEDED,
                            504,
                            "request deadline expired",
                            True,
                        )
                    candidate: _CredentialView | None = None
                    if provider.capabilities.key_required:
                        claimed = await _claim_credential(
                            control_plane,
                            organization_id=context.principal.organization_id,
                            provider=provider_name,
                            deadline_at=operation_deadline,
                        )
                        if claimed is None:
                            break
                        candidate = _credential_view(claimed)
                        if not _eligible_credential(candidate, now=datetime.now(UTC)):
                            continue
                    else:
                        candidate = next(
                            (
                                item
                                for item in provider_keys
                                if (item.key_id or item.api_key) not in attempted_keys
                            ),
                            None,
                        )
                    if candidate is None:
                        break
                    identity = (
                        candidate.key_id or f"{candidate.provider}:{candidate.api_key}"
                    )
                    if identity in attempted_keys:
                        break
                    attempted_keys.add(identity)
                    total_attempts += 1
                    acquired = False
                    succeeded = False
                    error: SearchServiceError | None = None
                    try:
                        await asyncio.wait_for(
                            provider_slots.acquire(), timeout=remaining
                        )
                        acquired = True
                        raw_results = await asyncio.wait_for(
                            provider.search(
                                operation=operation,
                                request=payload,
                                api_key=candidate.api_key,
                                deadline_at=operation_deadline,
                            ),
                            timeout=_remaining(operation_deadline),
                        )
                        results = tuple(
                            SearchResult.model_validate(item) for item in raw_results
                        )
                        succeeded = True
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
                    except asyncio.CancelledError:
                        raise
                    except TimeoutError as exc:
                        error = SearchServiceError(
                            SearchErrorCode.DEADLINE_EXCEEDED,
                            504,
                            "request deadline expired",
                            True,
                        )
                        raise error from exc
                    except ValidationError as exc:
                        error = SearchServiceError(
                            SearchErrorCode.UPSTREAM_MALFORMED,
                            502,
                            "provider response could not be normalized",
                        )
                        last_error = error
                        _LOGGER.warning(
                            "search_provider_failed",
                            extra={
                                "correlation_id": context.correlation_id,
                                "provider": provider.name,
                                "operation": operation.value,
                                "error_code": str(error.code),
                            },
                        )
                        del exc
                    except SearchServiceError as exc:
                        error = exc
                        last_error = exc
                        _LOGGER.warning(
                            "search_provider_failed",
                            extra={
                                "correlation_id": context.correlation_id,
                                "provider": provider.name,
                                "operation": operation.value,
                                "error_code": str(exc.code),
                            },
                        )
                        if exc.code in {
                            SearchErrorCode.INVALID_REQUEST,
                            SearchErrorCode.UNSUPPORTED_CAPABILITY,
                            SearchErrorCode.DEADLINE_EXCEEDED,
                        }:
                            raise
                    except Exception as exc:
                        error = SearchServiceError(
                            SearchErrorCode.UPSTREAM_UNAVAILABLE,
                            503,
                            "search provider is unavailable",
                            True,
                        )
                        last_error = error
                        _LOGGER.warning(
                            "search_provider_failed",
                            extra={
                                "correlation_id": context.correlation_id,
                                "provider": provider.name,
                                "operation": operation.value,
                                "error_code": str(error.code),
                            },
                        )
                        del exc
                    finally:
                        if acquired:
                            provider_slots.release()
                        if error is not None:
                            await _record_credential_failure(
                                control_plane,
                                organization_id=context.principal.organization_id,
                                credential=candidate,
                                error=error,
                                deadline_at=operation_deadline,
                            )
                        await _release_credential(
                            control_plane,
                            organization_id=context.principal.organization_id,
                            credential=candidate,
                            succeeded=succeeded,
                            deadline_at=operation_deadline,
                        )
                    if error is None:
                        break
                    if error.code == SearchErrorCode.DEADLINE_EXCEEDED:
                        raise error
                    if error.code == SearchErrorCode.UPSTREAM_MALFORMED:
                        # A malformed response is a provider-level failure;
                        # trying another key on the same adapter cannot fix it.
                        break
                    if total_attempts >= _MAX_ATTEMPTS:
                        break
                    if error.code in {
                        SearchErrorCode.UPSTREAM_UNAVAILABLE,
                        SearchErrorCode.UPSTREAM_MALFORMED,
                    }:
                        break
                    await _pause_before_retry(
                        error, attempt=total_attempts, deadline_at=operation_deadline
                    )
                if total_attempts >= _MAX_ATTEMPTS:
                    break
            if last_error is not None:
                raise last_error
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
                control_plane.get_settings(
                    organization_id=context.principal.organization_id
                ),
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
                    organization_id=context.principal.organization_id,
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
                    organization_id=context.principal.organization_id,
                    provider=payload.provider,
                    api_key=key,
                    label=payload.label,
                    suffix=_safe_suffix(key),
                    fingerprint=_fingerprint(key),
                    key_id=payload.key_id,
                )
            else:
                key_operation = control_plane.add_tested_key(
                    organization_id=context.principal.organization_id,
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
                    organization_id=context.principal.organization_id,
                    key_id=payload.key_id,
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

    @application.post("/v1/provider-keys/set-enabled")
    async def provider_key_set_enabled(request: Request) -> JSONResponse:
        correlation_id = "unknown"
        try:
            context, raw_input = await run_context_operation(request)
            correlation_id = context.correlation_id
            payload = ProviderKeySetEnabledInput.model_validate(raw_input)
            summary = await _call_control_plane(
                control_plane.set_key_enabled(
                    organization_id=context.principal.organization_id,
                    key_id=payload.key_id,
                    enabled=payload.enabled,
                ),
                deadline_at=context.deadline_at,
            )
            return success(
                context,
                ProviderKeyResult(
                    id=summary.id,
                    provider=summary.provider,
                    tested=summary.last_tested_at is not None,
                    active=summary.enabled,
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
                message="key enablement request is invalid",
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
                    control_plane.list_keys(
                        organization_id=context.principal.organization_id
                    ),
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
        self, *, organization_id: str
    ) -> tuple[ProviderCredential, ...]:
        raise RuntimeError("search control plane is not configured")

    async def claim_credential(
        self, *, organization_id: str, provider: str, lease_seconds: int = 30
    ) -> ProviderCredential | None:
        raise RuntimeError("search control plane is not configured")

    async def release_credential(
        self, *, organization_id: str, key_id: str, succeeded: bool = False
    ) -> None:
        raise RuntimeError("search control plane is not configured")

    async def record_key_failure(
        self,
        *,
        organization_id: str,
        key_id: str,
        status: str = "cooldown",
        cooldown_seconds: int = 30,
    ) -> None:
        raise RuntimeError("search control plane is not configured")

    async def record_provider_failure(
        self, *, organization_id: str, provider: str, cooldown_seconds: int = 30
    ) -> None:
        raise RuntimeError("search control plane is not configured")

    async def add_tested_key(
        self,
        *,
        organization_id: str,
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
        organization_id: str,
        provider: str,
        api_key: str,
        label: str,
        suffix: str,
        fingerprint: str,
        key_id: str,
    ) -> ProviderKeySummary:
        raise RuntimeError("search control plane is not configured")

    async def list_keys(
        self, *, organization_id: str
    ) -> tuple[ProviderKeySummary, ...]:
        raise RuntimeError("search control plane is not configured")

    async def delete_key(self, *, organization_id: str, key_id: str) -> None:
        raise RuntimeError("search control plane is not configured")

    async def set_key_enabled(
        self, *, organization_id: str, key_id: str, enabled: bool
    ) -> ProviderKeySummary:
        raise RuntimeError("search control plane is not configured")

    async def get_settings(self, *, organization_id: str) -> UserSettings:
        raise RuntimeError("search control plane is not configured")

    async def replace_settings(
        self, *, organization_id: str, providers: tuple[ProviderPreference, ...]
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
