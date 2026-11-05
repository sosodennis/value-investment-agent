"""Composition root for the independently deployable Fundamental service."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError
from src.shared.internal_services import INTERNAL_CONTRACT_VERSION

from .application import FundamentalApplication, UncertaintyRequestV1
from .application.service import normalize_uncertainty_payload
from .contracts import SnapshotResolutionRequestV1, ValuationInputV1
from .facts import CanonicalFactRepository
from .governance import ModelInventory
from .interface.transport import (
    authorize_operation,
    decode_input,
    error_response,
    readiness_response,
    success_response,
)
from .metadata import (
    PostgresArtifactStore,
    PostgresCanonicalFactRepository,
    PostgresContentStore,
    PostgresMetadataStore,
    PostgresSnapshotRepository,
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
from .policies import (
    MetadataModelRepository,
    MetadataPolicyRepository,
    PolicyRegistry,
    expansion_model_specs,
    expansion_policy_records,
    initial_model_specs,
    initial_policy_records,
)
from .replay import ArtifactStore, ReplayEnvelopeV1
from .snapshots import (
    ContentAddressedStore,
    FilesystemContentStore,
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
    artifact_store: Any = None,
    content_store: ContentAddressedStore | None = None,
    fact_repository: CanonicalFactRepository | None = None,
    *,
    config: OperationsConfig | None = None,
    metadata_store: PostgresMetadataStore | None = None,
    require_metadata: bool = False,
    policy_registry: PolicyRegistry | None = None,
    model_inventory: ModelInventory | None = None,
) -> FastAPI:
    """Assemble transport, application use cases, and runtime resources."""

    runtime_config = config or OperationsConfig.testing()
    if not require_metadata:
        # The explicit testing composition root owns disposable local evidence.
        # Production uses create_runtime_app and cannot reach this branch.
        if artifact_store is None:
            artifact_store = ArtifactStore(
                Path(tempfile.mkdtemp(prefix="fundamental-test-artifacts-"))
            )
        if content_store is None:
            content_store = FilesystemContentStore(
                Path(tempfile.mkdtemp(prefix="fundamental-test-content-"))
            )
        if policy_registry is None:
            policy_registry = PolicyRegistry(
                models=(*initial_model_specs(), *expansion_model_specs()),
                policies=(*initial_policy_records(), *expansion_policy_records()),
            )
    metrics = OperationalMetrics()
    limiter = RateLimiter(runtime_config.rate_limit_per_minute)
    application = FundamentalApplication(
        snapshot_repository=snapshot_repository,
        artifact_store=artifact_store,
        content_store=content_store,
        fact_repository=fact_repository,
        config=runtime_config,
        metrics=metrics,
        metadata_store=metadata_store,
        require_metadata=require_metadata,
        policy_registry=policy_registry,
        model_inventory=model_inventory,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if metadata_store is not None:
            try:
                metadata_store.start()
                if policy_registry is not None:
                    for model in (*initial_model_specs(), *expansion_model_specs()):
                        metadata_store.publish_model(
                            model,
                            model_id=model.model_id,
                            model_version=model.model_version,
                        )
                    for policy in (
                        *initial_policy_records(),
                        *expansion_policy_records(),
                    ):
                        metadata_store.publish_policy(
                            policy,
                            policy_id=policy.policy_id,
                            policy_version=policy.policy_version,
                        )
            except Exception:
                LOGGER.exception("fundamental metadata startup failed")
        app.state.accepting_requests = True
        try:
            yield
        finally:
            app.state.accepting_requests = False
            if metadata_store is not None:
                metadata_store.close()

    app = FastAPI(
        title="Fundamental service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.operations_config = runtime_config
    app.state.metrics = metrics
    app.state.application = application
    app.state.metadata_store = metadata_store
    app.state.model_inventory = model_inventory

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
    """Build production with PostgreSQL metadata and a content-only volume."""

    config = OperationsConfig.from_env()
    root_value = os.getenv("FUNDAMENTAL_SERVICE_DATA_ROOT")
    database_url = os.getenv("FUNDAMENTAL_SERVICE_DATABASE_URL")
    if not root_value or not database_url:
        return create_app(config=config, require_metadata=True)
    root = Path(root_value)
    metadata_store = PostgresMetadataStore(
        database_url,
        auto_migrate=os.getenv("FUNDAMENTAL_SERVICE_AUTO_MIGRATE", "0") == "1",
    )
    trust_roots_value = os.getenv("FUNDAMENTAL_MODEL_TRUST_ROOTS_FILE")
    model_inventory = ModelInventory.from_deployment_file(
        expansion_model_specs(),
        Path(trust_roots_value) if trust_roots_value else None,
    )
    content_store = PostgresContentStore(root / "content", metadata_store)
    return create_app(
        snapshot_repository=PostgresSnapshotRepository(metadata_store),
        artifact_store=PostgresArtifactStore(metadata_store, content_store),
        content_store=content_store,
        fact_repository=PostgresCanonicalFactRepository(metadata_store),
        config=config,
        metadata_store=metadata_store,
        require_metadata=True,
        model_inventory=model_inventory,
        policy_registry=PolicyRegistry(
            model_repository=MetadataModelRepository(metadata_store),
            repository=MetadataPolicyRepository(metadata_store),
        ),
    )


app = create_runtime_app()
