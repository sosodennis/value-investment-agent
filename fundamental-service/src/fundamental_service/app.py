"""Composition root for the independently deployable Fundamental service."""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError
from src.shared.internal_services import INTERNAL_CONTRACT_VERSION

from .application import FundamentalApplication, UncertaintyRequestV1
from .application.service import normalize_uncertainty_payload
from .contracts import SnapshotResolutionRequestV1, ValuationInputV1
from .facts import CanonicalFactRepository, FilesystemCanonicalFactRepository
from .interface.transport import (
    authorize_operation,
    decode_input,
    error_response,
    readiness_response,
    success_response,
)
from .operations import (
    CORRELATION_HEADER,
    OperationalMetrics,
    OperationsConfig,
    RateLimiter,
    ServiceError,
    correlation_id,
    guard_body_size,
)
from .replay import ArtifactStore, ReplayEnvelopeV1
from .snapshots import (
    ContentAddressedStore,
    FilesystemContentStore,
    FilesystemSnapshotRepository,
    SnapshotRepository,
)

LOGGER = logging.getLogger("fundamental_service")


def _validation_error(request: Request) -> JSONResponse:
    return error_response(
        request,
        ServiceError(
            "invalid_request",
            "request does not match the versioned service contract",
            status_code=400,
            retryable=False,
        ),
    )


def create_app(
    snapshot_repository: SnapshotRepository | None = None,
    artifact_store: ArtifactStore | None = None,
    content_store: ContentAddressedStore | None = None,
    fact_repository: CanonicalFactRepository | None = None,
    *,
    config: OperationsConfig | None = None,
) -> FastAPI:
    """Assemble transport, application use cases, and runtime resources."""

    runtime_config = config or OperationsConfig.testing()
    metrics = OperationalMetrics()
    limiter = RateLimiter(runtime_config.rate_limit_per_minute)
    application = FundamentalApplication(
        snapshot_repository=snapshot_repository,
        artifact_store=artifact_store,
        content_store=content_store,
        fact_repository=fact_repository,
        config=runtime_config,
        metrics=metrics,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.accepting_requests = True
        yield
        app.state.accepting_requests = False

    app = FastAPI(
        title="Fundamental service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.operations_config = runtime_config
    app.state.metrics = metrics
    app.state.application = application

    @app.middleware("http")
    async def operations_boundary(request: Request, call_next):
        started = monotonic()
        request.state.correlation_id = correlation_id(request)
        status_code = 500
        try:
            guard_body_size(request, runtime_config)
            if request.url.path.startswith("/v1/"):
                context, _ = await authorize_operation(request, runtime_config)
                if not limiter.allow(context.principal.subject_id):
                    metrics.increment("rate_limited_total")
                    raise ServiceError(
                        "request_rate_limited",
                        "request rate exceeds the synchronous service budget",
                        status_code=429,
                        retryable=True,
                    )
            response = await call_next(request)
            status_code = response.status_code
            deadline = getattr(request.state, "deadline", None)
            if deadline is not None and deadline <= datetime.now(UTC):
                metrics.increment("deadline_failures_total")
                if response.status_code < 400:
                    response = error_response(
                        request,
                        ServiceError(
                            "request_deadline_exceeded",
                            "request deadline expired before completion",
                            status_code=408,
                            retryable=True,
                        ),
                    )
                    status_code = response.status_code
            response.headers[CORRELATION_HEADER] = request.state.correlation_id
            return response
        except ServiceError as error:
            status_code = error.status_code
            if (
                error.code.startswith("internal_auth")
                or error.code == "invalid_context"
            ):
                metrics.increment("auth_failures_total")
            if error.code == "CALCULATION_BUDGET_EXCEEDED":
                metrics.increment("calculation_budget_failures_total")
            if error.code.startswith("request_deadline"):
                metrics.increment("deadline_failures_total")
            return error_response(request, error)
        except Exception:  # pragma: no cover - final redacted safety net
            status_code = 500
            return error_response(
                request,
                ServiceError(
                    "internal_failure",
                    "internal service failure",
                    status_code=500,
                    retryable=False,
                ),
            )
        finally:
            LOGGER.info(
                "fundamental_request",
                extra={
                    "correlation_id": request.state.correlation_id,
                    "path": request.url.path,
                    "status_code": status_code,
                    "elapsed_ms": round((monotonic() - started) * 1000, 3),
                },
            )
            metrics.observe_request(
                status_code=status_code,
                elapsed_ms=(monotonic() - started) * 1000,
            )

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, error: ServiceError):
        return error_response(request, error)

    @app.exception_handler(ValidationError)
    async def pydantic_validation_error_handler(
        request: Request, error: ValidationError
    ):
        _ = error
        return _validation_error(request)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request, error: RequestValidationError
    ):
        _ = error
        return _validation_error(request)

    @app.get("/livez")
    async def livez() -> dict[str, str]:
        return {"contract_version": INTERNAL_CONTRACT_VERSION, "status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        return readiness_response(ready=application.ready)

    @app.get("/metrics")
    async def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain")

    @app.get("/v1/data/snapshots/{snapshot_id}", response_model=None)
    async def get_snapshot(request: Request, snapshot_id: str) -> JSONResponse:
        return success_response(request, application.snapshot(snapshot_id))

    @app.post("/v1/data/snapshots/resolve", response_model=None)
    async def resolve_snapshot(request: Request) -> JSONResponse:
        value = decode_input(request, SnapshotResolutionRequestV1)
        return success_response(request, application.resolve_snapshot(value))

    @app.get("/v1/artifacts/{artifact_id}", response_model=None)
    async def get_artifact(request: Request, artifact_id: str) -> JSONResponse:
        return success_response(request, application.artifact(artifact_id))

    @app.get("/v1/artifacts/{artifact_id}/content")
    async def get_artifact_content(request: Request, artifact_id: str) -> Response:
        record, content = application.artifact_content(artifact_id)
        return Response(
            content=content,
            media_type=record.media_type,
            headers={
                "ETag": record.content_hash,
                CORRELATION_HEADER: request.state.correlation_id,
            },
        )

    @app.post("/v1/valuation/validate", response_model=None)
    async def validate_valuation(request: Request) -> JSONResponse:
        raw_input = request.state.operation_input
        if any(key in raw_input for key in ("scenarios", "sensitivity", "monte_carlo")):
            value = UncertaintyRequestV1.model_validate_json(
                json.dumps(normalize_uncertainty_payload(raw_input))
            )
            return success_response(request, application.validate_uncertainty(value))
        value = decode_input(request, ValuationInputV1)
        return success_response(request, application.validate_valuation(value))

    @app.post("/v1/valuation/calculate", response_model=None)
    async def calculate_valuation(request: Request) -> JSONResponse:
        value = decode_input(request, ValuationInputV1)
        result = application.calculate_valuation(
            value, correlation_id=request.state.correlation_id
        )
        return success_response(request, result)

    @app.post("/v1/valuation/replay", response_model=None)
    async def replay_valuation(request: Request) -> JSONResponse:
        envelope = decode_input(request, ReplayEnvelopeV1)
        return success_response(request, application.replay_valuation(envelope))

    @app.post("/v1/valuation/uncertainty", response_model=None)
    async def uncertainty_valuation(request: Request) -> JSONResponse:
        value = UncertaintyRequestV1.model_validate_json(
            json.dumps(normalize_uncertainty_payload(request.state.operation_input))
        )
        return success_response(request, application.uncertainty_valuation(value))

    return app


def create_runtime_app() -> FastAPI:
    """Build the production process with filesystem-owned immutable stores."""

    config = OperationsConfig.from_env()
    root_value = os.getenv("FUNDAMENTAL_SERVICE_DATA_ROOT")
    if not root_value:
        return create_app(config=config)
    root = Path(root_value)
    return create_app(
        snapshot_repository=FilesystemSnapshotRepository(root / "snapshots"),
        artifact_store=ArtifactStore(root / "artifacts"),
        content_store=FilesystemContentStore(root / "content"),
        fact_repository=FilesystemCanonicalFactRepository(root / "facts"),
        config=config,
    )


app = create_runtime_app()
