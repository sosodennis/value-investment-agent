"""Shared internal-service HTTP parsing, authentication, and envelopes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Generic, Literal, TypeVar

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
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

from ..operations import (
    AUTH_HEADER,
    CORRELATION_HEADER,
    OperationsConfig,
    ServiceError,
    correlation_id,
    enforce_deadline,
)


class FundamentalRequestEnvelopeV1(BaseModel):
    """The only accepted operation request shape at the service boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    context: InternalRequestContext
    input: dict[str, object]


RequestInput = TypeVar("RequestInput", bound=BaseModel)
ResponseResult = TypeVar("ResponseResult", bound=BaseModel)


class TypedFundamentalRequestEnvelopeV1(BaseModel, Generic[RequestInput]):
    """Operation-specific input schema with the shared signed context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    context: InternalRequestContext
    input: RequestInput


class TypedFundamentalResponseEnvelopeV1(BaseModel, Generic[ResponseResult]):
    """OpenAPI response schema for the shared and service-owned envelopes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    correlation_id: str
    contract_version: Literal[INTERNAL_CONTRACT_VERSION]
    schema_version: Literal["fundamental.v1"]
    result: ResponseResult


class EmptyOperationInputV1(BaseModel):
    """Empty typed input used by authenticated path-based read operations."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FundamentalResponseEnvelopeV1(BaseModel):
    """Shared metadata plus the service-owned ``fundamental.v1`` result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    correlation_id: str
    contract_version: Literal[INTERNAL_CONTRACT_VERSION]
    schema_version: Literal["fundamental.v1"]
    result: dict[str, object]


_JSON_OBJECT = TypeAdapter(dict[str, object])


def _correlation_from_raw(raw: object, request: Request) -> str:
    if isinstance(raw, Mapping):
        context = raw.get("context")
        if isinstance(context, Mapping):
            value = context.get("correlation_id")
            if isinstance(value, str) and 0 < len(value) <= 128:
                return value
    return correlation_id(request)


async def authorize_operation(
    request: Request, config: OperationsConfig
) -> tuple[InternalRequestContext, dict[str, object]]:
    """Parse and authenticate one signed internal operation envelope."""

    try:
        raw = _JSON_OBJECT.validate_json(await request.body())
    except (ValidationError, ValueError, TypeError) as exc:
        raise ServiceError(
            "invalid_request",
            "request body is invalid",
            status_code=400,
            retryable=False,
        ) from exc

    request.state.correlation_id = _correlation_from_raw(raw, request)
    if set(raw) != {"context", "input"} or not isinstance(raw["input"], Mapping):
        raise ServiceError(
            "invalid_request",
            "request must contain context and input",
            status_code=400,
            retryable=False,
        )
    raw_context = raw["context"]
    if not isinstance(raw_context, Mapping):
        raise ServiceError(
            "invalid_context",
            "request context is invalid",
            status_code=400,
            retryable=False,
        )

    try:
        context = authenticate_internal_request(
            request.headers.get(AUTH_HEADER),
            expected_token=config.service_token,
            raw_context=raw_context,
            expected_audience="fundamental-service",
            expected_issuer=INTERNAL_CONTEXT_ISSUER,
            signing_key=config.service_token,
            organization_header=request.headers.get("X-Organization-ID"),
        )
    except InternalAuthenticationError as exc:
        raise ServiceError(
            exc.code, str(exc), status_code=401, retryable=False
        ) from exc
    except InternalContextValidationError as exc:
        raise ServiceError(
            "invalid_context",
            "request context is invalid",
            status_code=400,
            retryable=False,
        ) from exc

    if context.principal.organization_id in {
        None,
        "unscoped",
    } or context.principal.membership_id in {
        None,
        "unscoped",
    }:
        raise ServiceError(
            "internal_context_claims_invalid",
            "request context claims are invalid",
            status_code=401,
            retryable=False,
        )

    request.state.context = context
    request.state.correlation_id = context.correlation_id
    request.state.deadline = enforce_deadline(context.deadline_at, config)
    request.state.operation_input = dict(raw["input"])
    return context, request.state.operation_input


def error_response(request: Request, error: ServiceError) -> JSONResponse:
    correlation = getattr(request.state, "correlation_id", "unknown")
    body = InternalErrorResponse(
        correlation_id=correlation,
        contract_version=INTERNAL_CONTRACT_VERSION,
        error=InternalError(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
        ),
    )
    return JSONResponse(
        status_code=error.status_code,
        content=body.model_dump(mode="json"),
        headers={CORRELATION_HEADER: correlation},
    )


def success_response(
    request: Request, result: BaseModel | Mapping[str, object]
) -> JSONResponse:
    context = getattr(request.state, "context", None)
    if not isinstance(context, InternalRequestContext):
        raise RuntimeError("successful operation is missing its authenticated context")
    payload = (
        result.model_dump(mode="json")
        if isinstance(result, BaseModel)
        else dict(result)
    )
    body = FundamentalResponseEnvelopeV1(
        correlation_id=context.correlation_id,
        contract_version=INTERNAL_CONTRACT_VERSION,
        schema_version="fundamental.v1",
        result=payload,
    )
    return JSONResponse(
        content=body.model_dump(mode="json"),
        headers={CORRELATION_HEADER: context.correlation_id},
    )


def readiness_response(*, ready: bool) -> JSONResponse:
    body = InternalReadiness(
        status=ReadinessStatus.READY if ready else ReadinessStatus.NOT_READY,
        contract_version=INTERNAL_CONTRACT_VERSION,
    )
    return JSONResponse(
        status_code=200 if ready else 503,
        content=body.model_dump(mode="json"),
    )


def decode_input(request: Request, model: type[BaseModel]) -> BaseModel:
    """Decode JSON wire values through the model's strict JSON boundary."""

    return model.model_validate_json(json.dumps(request.state.operation_input))


__all__ = [
    "EmptyOperationInputV1",
    "FundamentalRequestEnvelopeV1",
    "FundamentalResponseEnvelopeV1",
    "TypedFundamentalRequestEnvelopeV1",
    "TypedFundamentalResponseEnvelopeV1",
    "authorize_operation",
    "decode_input",
    "error_response",
    "readiness_response",
    "success_response",
]
