"""HTTP boundary for the isolated Fundamental service."""

from __future__ import annotations

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

from .calculator import CalculationRefusal, calculate, validate
from .contracts import (
    CalculationArtifactV1,
    FundamentalError,
    SourceSnapshotV1,
    StatusResponseV1,
    ValidationResponseV1,
    ValuationInputV1,
)
from .operations import (
    CORRELATION_HEADER,
    OperationalMetrics,
    OperationsConfig,
    RateLimiter,
    ServiceError,
    authenticate,
    correlation_id,
    enforce_deadline,
    guard_body_size,
    guard_calculation_budget,
)
from .replay import (
    ArtifactRecordV1,
    ArtifactStore,
    ReplayEnvelopeV1,
    ReplayReportV1,
    replay_manifest,
)
from .snapshots import (
    ContentAddressedStore,
    FilesystemContentStore,
    FilesystemSnapshotRepository,
    SnapshotError,
    SnapshotRepository,
)
from .uncertainty import (
    MonteCarloRequestV1,
    ScenarioV1,
    SensitivityRequestV1,
    UncertaintyReportV1,
    run_uncertainty,
)

LOGGER = logging.getLogger("fundamental_service")


class UncertaintyRequestV1(ValuationInputV1):
    """HTTP input carrying explicit uncertainty controls alongside valuation input."""

    scenarios: tuple[ScenarioV1, ...] = ()
    sensitivity: tuple[SensitivityRequestV1, ...] = ()
    monte_carlo: MonteCarloRequestV1 | None = None


def _error_response(request: Request, error: ServiceError) -> JSONResponse:
    value = FundamentalError(
        code=error.code,
        message=error.message,
        correlation_id=getattr(request.state, "correlation_id", "unknown"),
        retryable=error.retryable,
    )
    return JSONResponse(
        status_code=error.status_code,
        content=value.model_dump(mode="json"),
        headers={CORRELATION_HEADER: value.correlation_id},
    )


def _validation_error(request: Request) -> JSONResponse:
    return _error_response(
        request,
        ServiceError(
            "REQUEST_INVALID",
            "request does not match the versioned service contract",
            status_code=400,
            retryable=False,
        ),
    )


def _snapshot_error(error: SnapshotError) -> ServiceError:
    if error.code in {"SNAPSHOT_NOT_FOUND", "ARTIFACT_NOT_FOUND"}:
        return ServiceError(
            error.code,
            "requested immutable evidence was not found",
            status_code=404,
            retryable=False,
        )
    return ServiceError(
        error.code,
        "immutable evidence is temporarily unavailable",
        status_code=503,
        retryable=error.retryable or error.code.endswith("UNAVAILABLE"),
    )


def _require_snapshot(
    repository: SnapshotRepository | None,
    snapshot_id: str,
    metrics: OperationalMetrics,
) -> SourceSnapshotV1 | object:
    if repository is None:
        metrics.increment("source_health_failures_total")
        raise ServiceError(
            "SOURCE_UNAVAILABLE",
            "selected immutable snapshot is unavailable",
            status_code=503,
            retryable=True,
        )
    try:
        return repository.get(snapshot_id)
    except SnapshotError as error:
        metrics.increment("source_health_failures_total")
        raise _snapshot_error(error) from error
    except Exception as error:  # pragma: no cover - defensive provider boundary
        metrics.increment("source_health_failures_total")
        raise ServiceError(
            "SOURCE_UNAVAILABLE",
            "selected immutable snapshot is unavailable",
            status_code=503,
            retryable=True,
        ) from error


def create_app(
    snapshot_repository: SnapshotRepository | None = None,
    artifact_store: ArtifactStore | None = None,
    content_store: ContentAddressedStore | None = None,
    *,
    config: OperationsConfig | None = None,
) -> FastAPI:
    # Direct construction is the explicit unit-test seam.  The process-level app
    # below always passes an environment-backed production configuration.
    config = config or OperationsConfig.testing()
    metrics = OperationalMetrics()
    limiter = RateLimiter(config.rate_limit_per_minute)

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
    app.state.operations_config = config
    app.state.metrics = metrics

    @app.middleware("http")
    async def operations_boundary(request: Request, call_next):
        started = monotonic()
        request.state.correlation_id = correlation_id(request)
        status_code = 500
        try:
            guard_body_size(request, config)
            deadline = enforce_deadline(request, config)
            request.state.deadline = deadline
            protected = (
                request.url.path.startswith("/v1/") or request.url.path == "/metrics"
            )
            if protected:
                subject = authenticate(request, config)
                request.state.auth_subject = subject
                if not limiter.allow(subject):
                    metrics.increment("rate_limited_total")
                    raise ServiceError(
                        "REQUEST_RATE_LIMITED",
                        "request rate exceeds the synchronous service budget",
                        status_code=429,
                        retryable=True,
                    )
            response = await call_next(request)
            status_code = response.status_code
            if deadline is not None and deadline <= datetime.now(UTC):
                metrics.increment("deadline_failures_total")
                if response.status_code < 400:
                    response = _error_response(
                        request,
                        ServiceError(
                            "REQUEST_DEADLINE_EXCEEDED",
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
            if error.code.startswith("AUTHENTICATION"):
                metrics.increment("auth_failures_total")
            if error.code == "CALCULATION_BUDGET_EXCEEDED":
                metrics.increment("calculation_budget_failures_total")
            if error.code.startswith("REQUEST_DEADLINE"):
                metrics.increment("deadline_failures_total")
            return _error_response(request, error)
        except (
            Exception  # noqa: BLE001
        ) as _error:  # pragma: no cover - final redacted safety net
            return _error_response(
                request,
                ServiceError(
                    "INTERNAL_FAILURE",
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
        return _error_response(request, error)

    @app.exception_handler(ValidationError)
    async def pydantic_validation_error_handler(
        request: Request, error: ValidationError
    ):
        return _validation_error(request)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request, error: RequestValidationError
    ):
        return _validation_error(request)

    @app.get("/livez", response_model=StatusResponseV1)
    async def livez() -> StatusResponseV1:
        return StatusResponseV1(contract_version="internal.v1", status="ok")

    @app.get("/readyz", response_model=StatusResponseV1)
    async def readyz(response: Response) -> StatusResponseV1:
        ready = (
            snapshot_repository is not None
            and artifact_store is not None
            and content_store is not None
            and config.auth_ready
        )
        response.status_code = 200 if ready else 503
        return StatusResponseV1(
            contract_version="internal.v1",
            status="ok" if ready else "not_ready",
        )

    @app.get("/metrics")
    async def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain")

    @app.get("/v1/data/snapshots/{snapshot_id}", response_model=SourceSnapshotV1)
    async def get_snapshot(snapshot_id: str) -> SourceSnapshotV1:
        if snapshot_repository is None:
            raise ServiceError(
                "SOURCE_UNAVAILABLE",
                "selected immutable snapshot is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            return snapshot_repository.get(snapshot_id)
        except SnapshotError as error:
            raise _snapshot_error(error) from error

    @app.get("/v1/artifacts/{artifact_id}", response_model=ArtifactRecordV1)
    async def get_artifact(artifact_id: str) -> ArtifactRecordV1:
        if artifact_store is None:
            raise ServiceError(
                "SOURCE_UNAVAILABLE",
                "released artifact is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            return artifact_store.get(artifact_id)
        except SnapshotError as error:
            raise _snapshot_error(error) from error

    @app.get("/v1/artifacts/{artifact_id}/content")
    async def get_artifact_content(artifact_id: str) -> Response:
        if artifact_store is None:
            raise ServiceError(
                "SOURCE_UNAVAILABLE",
                "released artifact is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            record = artifact_store.get(artifact_id)
            return Response(
                content=artifact_store.read(artifact_id),
                media_type=record.media_type,
                headers={"ETag": record.content_hash},
            )
        except SnapshotError as error:
            raise _snapshot_error(error) from error

    @app.post("/v1/valuation/validate", response_model=ValidationResponseV1)
    async def validate_valuation(request: Request) -> ValidationResponseV1:
        value = ValuationInputV1.model_validate_json(await request.body())
        _require_snapshot(
            snapshot_repository, value.valuation_context.data_snapshot_id, metrics
        )
        resolved = validate(value)
        return ValidationResponseV1(
            contract_version="fundamental.v1",
            input=resolved,
            input_digest=resolved.input_digest,
            quality_status=resolved.quality.status,
            issue_codes=resolved.quality.issue_codes,
            missing_evidence=resolved.quality.missing_evidence,
        )

    @app.post("/v1/valuation/calculate", response_model=CalculationArtifactV1)
    async def calculate_valuation(request: Request) -> CalculationArtifactV1:
        value = ValuationInputV1.model_validate_json(await request.body())
        guard_calculation_budget(value, config)
        _require_snapshot(
            snapshot_repository, value.valuation_context.data_snapshot_id, metrics
        )
        try:
            result = calculate(value, correlation_id=request.state.correlation_id)
        except CalculationRefusal as error:
            raise ServiceError(
                error.code,
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        metrics.increment("quality_status_total")
        metrics.increment(f"quality_status_{result.quality_status.value}_total")
        return result

    @app.post("/v1/valuation/replay", response_model=ReplayReportV1)
    async def replay_valuation(request: Request) -> ReplayReportV1:
        if artifact_store is None or snapshot_repository is None:
            metrics.increment("provenance_replay_failures_total")
            raise ServiceError(
                "SOURCE_UNAVAILABLE",
                "replay dependencies are unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            envelope = ReplayEnvelopeV1.model_validate_json(await request.body())
            report = replay_manifest(
                envelope,
                artifact_store=artifact_store,
                snapshot_repository=snapshot_repository,
            )
            if report.status.value in {"abstain", "degraded"}:
                metrics.increment("abstention_total")
            return report
        except (ValueError, SnapshotError) as error:
            metrics.increment("provenance_replay_failures_total")
            if isinstance(error, SnapshotError):
                raise _snapshot_error(error) from error
            raise ServiceError(
                "REPLAY_MISMATCH",
                "released evidence did not reproduce",
                status_code=422,
                retryable=False,
            ) from error

    @app.post("/v1/valuation/uncertainty", response_model=UncertaintyReportV1)
    async def uncertainty_valuation(request: Request) -> UncertaintyReportV1:
        value = UncertaintyRequestV1.model_validate_json(await request.body())
        guard_calculation_budget(value, config)
        _require_snapshot(
            snapshot_repository, value.valuation_context.data_snapshot_id, metrics
        )
        try:
            result = run_uncertainty(
                value,
                monte_carlo=value.monte_carlo,
                scenarios=value.scenarios,
                sensitivity=value.sensitivity,
            )
        except (CalculationRefusal, ValueError) as error:
            raise ServiceError(
                getattr(error, "code", "UNCERTAINTY_INVALID"),
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        metrics.increment("quality_status_total")
        metrics.increment(f"quality_status_{result.status.value}_total")
        if result.status.value in {"abstain", "degraded"}:
            metrics.increment("abstention_total")
        return result

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
        config=config,
    )


app = create_runtime_app()
