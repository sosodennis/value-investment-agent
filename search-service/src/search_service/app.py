from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Mapping
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from src.shared.internal_services import (
    INTERNAL_CONTRACT_VERSION,
    InternalAuthenticationError,
    InternalContextValidationError,
    InternalRequestContext,
    authenticate_internal_request,
)

from .contracts import (
    ErrorBody,
    NewsSearchRequest,
    Operation,
    ProviderKeyInput,
    ProviderKeyList,
    ProviderKeyResult,
    SearchErrorCode,
    SearchFailure,
    SearchRequestBase,
    SearchSuccess,
    WebSearchRequest,
)
from .errors import SearchServiceError
from .ports import SearchControlPlane, SearchProvider, requested_capabilities


def _remaining(deadline_at: datetime) -> float:
    return (deadline_at - datetime.now(UTC)).total_seconds()


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
    application = FastAPI(title="Private Search Service", version="1.0")
    provider_slots = asyncio.Semaphore(32)

    def context_for(request: Request, raw: object) -> InternalRequestContext:
        context_raw = raw.get("context", {}) if isinstance(raw, dict) else {}
        if not isinstance(context_raw, dict):
            context_raw = {}
        return authenticate_internal_request(
            request.headers.get("Authorization"),
            expected_token=service_token,
            raw_context=context_raw,
        )

    def error_response(
        correlation_id: str,
        code: SearchErrorCode,
        message: str,
        status: int,
        *,
        retryable: bool = False,
        retry_after_ms: int | None = None,
    ) -> JSONResponse:
        response = SearchFailure(
            contract_version=INTERNAL_CONTRACT_VERSION,
            schema_version="search.v1",
            correlation_id=correlation_id,
            error=ErrorBody(
                code=code,
                message=message,
                retryable=retryable,
                retry_after_ms=retry_after_ms,
            ),
        )
        return JSONResponse(
            status_code=status, content=response.model_dump(mode="json")
        )

    async def read_body(request: Request) -> object:
        try:
            return await request.json()
        except Exception as exc:
            raise SearchServiceError(
                SearchErrorCode.INVALID_ARGUMENT, 400, "request body is invalid"
            ) from exc

    async def search(request: Request, operation: Operation) -> JSONResponse:
        correlation_id = "unknown"
        try:
            raw = await read_body(request)
            correlation_id = _correlation_id(raw)
            context = context_for(request, raw)
            correlation_id = context.correlation_id
            if not isinstance(raw, dict) or not isinstance(raw.get("input"), dict):
                raise SearchServiceError(
                    SearchErrorCode.INVALID_ARGUMENT, 400, "search input is invalid"
                )
            request_model: type[SearchRequestBase] = (
                WebSearchRequest if operation is Operation.WEB else NewsSearchRequest
            )
            payload = request_model.model_validate(raw["input"])
            if _remaining(context.deadline_at) <= 0:
                raise SearchServiceError(
                    SearchErrorCode.DEADLINE_EXCEEDED,
                    504,
                    "request deadline expired",
                    True,
                )

            credentials = await control_plane.credentials_for(
                subject_id=context.principal.subject_id
            )
            providers_by_name = providers
            requested = requested_capabilities(payload)
            eligible: list[tuple[int, str, SearchProvider, str]] = []
            for credential in credentials:
                provider = providers_by_name.get(credential.provider)
                if not credential.enabled or not credential.api_key or provider is None:
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

            for _priority, _name, provider, api_key in sorted(eligible)[:3]:
                remaining = _remaining(context.deadline_at)
                if remaining <= 0:
                    raise SearchServiceError(
                        SearchErrorCode.DEADLINE_EXCEEDED,
                        504,
                        "request deadline expired",
                        True,
                    )
                try:
                    await asyncio.wait_for(provider_slots.acquire(), timeout=remaining)
                    try:
                        results = await asyncio.wait_for(
                            provider.search(
                                operation=operation,
                                request=payload,
                                api_key=api_key,
                                deadline_at=context.deadline_at,
                            ),
                            timeout=_remaining(context.deadline_at),
                        )
                    finally:
                        provider_slots.release()
                    response = SearchSuccess(
                        contract_version=INTERNAL_CONTRACT_VERSION,
                        schema_version="search.v1",
                        correlation_id=context.correlation_id,
                        operation=operation,
                        results=results[: payload.limit],
                    )
                    return JSONResponse(content=response.model_dump(mode="json"))
                except TimeoutError as exc:
                    raise SearchServiceError(
                        SearchErrorCode.DEADLINE_EXCEEDED,
                        504,
                        "request deadline expired",
                        True,
                    ) from exc
                except SearchServiceError:
                    continue
                except Exception:
                    continue
            raise SearchServiceError(
                SearchErrorCode.UPSTREAM_UNAVAILABLE,
                503,
                "search providers are unavailable",
                True,
                250,
            )
        except InternalAuthenticationError as exc:
            return error_response(
                correlation_id,
                SearchErrorCode.UNAUTHENTICATED,
                str(exc),
                401,
            )
        except InternalContextValidationError:
            return error_response(
                correlation_id,
                SearchErrorCode.INVALID_ARGUMENT,
                "request context is invalid",
                400,
            )
        except ValidationError:
            return error_response(
                correlation_id,
                SearchErrorCode.INVALID_ARGUMENT,
                "search input failed validation",
                400,
            )
        except SearchServiceError as exc:
            return error_response(
                correlation_id,
                exc.code,
                exc.message,
                exc.status_code,
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
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "not_ready",
                "contract_version": INTERNAL_CONTRACT_VERSION,
            },
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
        return await search(request, Operation.WEB)

    @application.post("/v1/search/news")
    async def news_search(request: Request) -> JSONResponse:
        return await search(request, Operation.NEWS)

    @application.post("/v1/provider-keys/{provider}/{action}")
    async def change_provider_key(
        provider: str, action: str, request: Request
    ) -> JSONResponse:
        correlation_id = "unknown"
        try:
            raw = await read_body(request)
            correlation_id = _correlation_id(raw)
            context = context_for(request, raw)
            correlation_id = context.correlation_id
            if not isinstance(raw, dict) or not isinstance(raw.get("input"), dict):
                raise SearchServiceError(
                    SearchErrorCode.INVALID_ARGUMENT, 400, "key input is invalid"
                )
            payload = ProviderKeyInput.model_validate(raw["input"])
            configured = providers.get(provider)
            if configured is None:
                raise SearchServiceError(
                    SearchErrorCode.UNSUPPORTED_CAPABILITY,
                    422,
                    "provider is not configured",
                )
            key = payload.api_key.get_secret_value()
            if _remaining(context.deadline_at) <= 0:
                raise SearchServiceError(
                    SearchErrorCode.DEADLINE_EXCEEDED,
                    504,
                    "request deadline expired",
                    True,
                )
            tested = await asyncio.wait_for(
                configured.test_key(key, deadline_at=context.deadline_at),
                timeout=_remaining(context.deadline_at),
            )
            if not tested:
                raise SearchServiceError(
                    SearchErrorCode.UPSTREAM_UNAVAILABLE,
                    422,
                    "provider key test failed",
                )
            fingerprint = _fingerprint(key)
            if action == "delete":
                await control_plane.delete_key(
                    subject_id=context.principal.subject_id,
                    provider=provider,
                )
                return JSONResponse(
                    content={
                        "contract_version": INTERNAL_CONTRACT_VERSION,
                        "schema_version": "search.v1",
                        "correlation_id": correlation_id,
                        "result": {"deleted": True},
                    }
                )
            if action not in {"add", "replace"}:
                raise SearchServiceError(
                    SearchErrorCode.INVALID_ARGUMENT,
                    404,
                    "key operation is unsupported",
                )
            write_key = (
                control_plane.add_tested_key
                if action == "add"
                else control_plane.replace_tested_key
            )
            summary = await write_key(
                subject_id=context.principal.subject_id,
                provider=provider,
                api_key=key,
                label=payload.label,
                suffix=_safe_suffix(key),
                fingerprint=fingerprint,
            )
            body = ProviderKeyResult(
                provider=provider,
                tested=True,
                active=True,
                suffix=summary.suffix,
                fingerprint=summary.fingerprint,
            )
            return JSONResponse(
                content={
                    "contract_version": INTERNAL_CONTRACT_VERSION,
                    "schema_version": "search.v1",
                    "correlation_id": correlation_id,
                    "result": body.model_dump(mode="json"),
                }
            )
        except InternalAuthenticationError:
            return error_response(
                correlation_id,
                SearchErrorCode.UNAUTHENTICATED,
                "service authentication failed",
                401,
            )
        except (InternalContextValidationError, ValidationError):
            return error_response(
                correlation_id,
                SearchErrorCode.INVALID_ARGUMENT,
                "key request is invalid",
                400,
            )
        except SearchServiceError as exc:
            return error_response(
                correlation_id,
                exc.code,
                exc.message,
                exc.status_code,
                retryable=exc.retryable,
                retry_after_ms=exc.retry_after_ms,
            )
        except TimeoutError:
            return error_response(
                correlation_id,
                SearchErrorCode.DEADLINE_EXCEEDED,
                "request deadline expired",
                504,
                retryable=True,
            )

    @application.post("/v1/provider-keys/list")
    async def list_provider_keys(request: Request) -> JSONResponse:
        correlation_id = "unknown"
        try:
            raw = await read_body(request)
            correlation_id = _correlation_id(raw)
            context = context_for(request, raw)
            correlation_id = context.correlation_id
            keys = await control_plane.list_keys(
                subject_id=context.principal.subject_id
            )
            body = ProviderKeyList(providers=keys)
            return JSONResponse(
                content={
                    "contract_version": INTERNAL_CONTRACT_VERSION,
                    "schema_version": "search.v1",
                    "correlation_id": correlation_id,
                    "result": body.model_dump(mode="json"),
                }
            )
        except InternalAuthenticationError:
            return error_response(
                correlation_id,
                SearchErrorCode.UNAUTHENTICATED,
                "service authentication failed",
                401,
            )
        except InternalContextValidationError:
            return error_response(
                correlation_id,
                SearchErrorCode.INVALID_ARGUMENT,
                "request context is invalid",
                400,
            )

    @application.post("/v1/settings/provider")
    async def update_provider_settings(request: Request) -> JSONResponse:
        correlation_id = "unknown"
        try:
            raw = await read_body(request)
            correlation_id = _correlation_id(raw)
            context = context_for(request, raw)
            correlation_id = context.correlation_id
            if not isinstance(raw, dict) or not isinstance(raw.get("input"), dict):
                raise SearchServiceError(
                    SearchErrorCode.INVALID_ARGUMENT,
                    400,
                    "provider settings are invalid",
                )
            values = raw["input"]
            provider = values.get("provider")
            enabled = values.get("enabled")
            priority = values.get("priority")
            if (
                not isinstance(provider, str)
                or not provider
                or not isinstance(enabled, bool)
                or not isinstance(priority, int)
                or priority < 0
            ):
                raise SearchServiceError(
                    SearchErrorCode.INVALID_ARGUMENT,
                    400,
                    "provider settings are invalid",
                )
            if provider not in providers:
                raise SearchServiceError(
                    SearchErrorCode.UNSUPPORTED_CAPABILITY,
                    422,
                    "provider is not configured",
                )
            await control_plane.update_provider(
                subject_id=context.principal.subject_id,
                provider=provider,
                enabled=enabled,
                priority=priority,
            )
            return JSONResponse(
                content={
                    "contract_version": INTERNAL_CONTRACT_VERSION,
                    "schema_version": "search.v1",
                    "correlation_id": correlation_id,
                    "result": {
                        "provider": provider,
                        "enabled": enabled,
                        "priority": priority,
                    },
                }
            )
        except InternalAuthenticationError:
            return error_response(
                correlation_id,
                SearchErrorCode.UNAUTHENTICATED,
                "service authentication failed",
                401,
            )
        except InternalContextValidationError:
            return error_response(
                correlation_id,
                SearchErrorCode.INVALID_ARGUMENT,
                "request context is invalid",
                400,
            )
        except SearchServiceError as exc:
            return error_response(
                correlation_id, exc.code, exc.message, exc.status_code
            )

    return application


class _UnavailableControlPlane:
    async def credentials_for(self, *, subject_id: str) -> tuple[object, ...]:
        raise RuntimeError("search control plane is not configured")

    async def add_tested_key(self, **_values: object) -> object:
        raise RuntimeError("search control plane is not configured")

    async def replace_tested_key(self, **_values: object) -> object:
        raise RuntimeError("search control plane is not configured")

    async def list_keys(self, *, subject_id: str) -> tuple[object, ...]:
        raise RuntimeError("search control plane is not configured")

    async def delete_key(self, *, subject_id: str, provider: str) -> None:
        raise RuntimeError("search control plane is not configured")

    async def update_provider(self, **_values: object) -> None:
        raise RuntimeError("search control plane is not configured")


app = create_app(providers={}, control_plane=_UnavailableControlPlane())
