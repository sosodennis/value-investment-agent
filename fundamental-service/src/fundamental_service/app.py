"""Composition root for the independently deployable Fundamental service."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import get_ident
from time import monotonic
from typing import Any, Literal, ParamSpec, TypeVar

from anyio import CapacityLimiter, fail_after, to_thread
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError
from src.shared.internal_services import INTERNAL_CONTRACT_VERSION
from starlette.concurrency import run_in_threadpool

from .application import FundamentalApplication, UncertaintyRequestV1
from .application.service import normalize_uncertainty_payload
from .original_preparation import OriginalPreparation
from .statement_contracts import (
    AnnualStatementsReadRequestV1,
    AnnualStatementsReadResponseV1,
)
from .valuation_diagnostics import (
    ValuationDiagnosticSink,
    diagnostic_error_code,
    valuation_diagnostic_scope,
)
from .contracts import (
    CalculationArtifactV1,
    FactsReadRequestV1,
    FactsReadResponseV1,
    IdentityResolutionRequestV1,
    IdentityResolutionV1,
    PolicyValuationInputV1,
    SecIngestionRequestV1,
    SecIngestionResponseV1,
    SnapshotResolutionRequestV1,
    ValuationEvidenceReadRequestV1,
    ValuationEvidenceReadResponseV1,
    ValuationInputV1,
)
from .data_releases import (
    ActiveDataReleaseWithManifestV1,
    DataReleaseActivationRequestV1,
    DataReleaseCandidatePublishRequestV1,
    DataReleaseCandidateReceiptV1,
    DataReleaseTrustRootsV1,
)
from .facts import CanonicalFactRepository
from .quote_providers import QuoteSourceProviderPort
from .quote_sources import default_quote_providers
from .free_source_policy import (
    default_macro_providers,
    default_reference_providers,
    free_market_source_policy,
)
from .macro_series import MacroSeriesProviderPort
from .market_reference import MarketReferenceProviderPort
from .source_admission import SourceUsePolicyV1
from .source_use_deployment import load_runtime_source_use_policy
from .governance import ModelInventory
from .model_release_deployment import load_model_release_deployment
from .conditional_revision import RevisionActor
from .interface.transport import (
    EmptyOperationInputV1,
    TypedFundamentalRequestEnvelopeV1,
    TypedFundamentalResponseEnvelopeV1,
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
    REQUEST_LOG_ID_HEADER,
    RequestLogContext,
    ServiceError,
    correlation_id,
    create_request_log_context,
    guard_body_size,
    guard_execution_deadline,
)
from .policies import (
    MetadataModelRepository,
    MetadataPolicyRepository,
    PolicyRecordV1,
    PolicyRegistry,
    dated_model_specs,
    executable_model_specs,
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
from .source_acquisition import (
    SecAcquisitionUseCase,
    SecIdentityResolutionUseCase,
    build_runtime_sec_acquisition,
    build_runtime_sec_identity_resolution,
    parse_supported_filing_forms,
    parse_supported_filing_years,
)
from .uncertainty import UncertaintyReportV1
from .valuation_preparation import (
    AutomaticValuationPreparationV1,
    ManualValuationOverrideRequestV1,
)
from .forward_evidence import (
    ForwardEvidenceReviewRequestV1,
    ForwardEvidenceReviewResponseV1,
)

LOGGER = logging.getLogger("fundamental_service")
P = ParamSpec("P")
T = TypeVar("T")


def _log_valuation_diagnostic(
    *,
    request: Request,
    sink: ValuationDiagnosticSink,
    operation: str | None,
    event: str,
    trace_started: float,
    deadline_at: datetime | None,
    **fields: object,
) -> None:
    """Emit one machine-readable, opt-in execution phase record."""
    log_context = getattr(request.state, "log_context", None)
    if not isinstance(log_context, RequestLogContext):
        return
    payload: dict[str, object] = {
        "event": event,
        "request_log_id": log_context.request_log_id,
        "route_template": log_context.route_template,
        "operation": operation,
        "timestamp": datetime.now(UTC).isoformat(),
        "elapsed_ms": round((monotonic() - trace_started) * 1000, 3),
        "deadline_at": deadline_at.isoformat() if deadline_at is not None else None,
        "deadline_remaining_ms": (
            round((deadline_at - datetime.now(UTC)).total_seconds() * 1000, 3)
            if deadline_at is not None
            else None
        ),
        "diagnostic_sink": sink.status(),
        **fields,
    }
    sink.submit(
        "fundamental_valuation_diagnostic",
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        extra={
            "request_log_id": log_context.request_log_id,
            "valuation_diagnostic_event": event,
        },
    )


def _validation_error(
    request: Request, error: ValidationError | RequestValidationError | None = None
) -> JSONResponse:
    log_context = getattr(request.state, "log_context", None)
    if error is not None and isinstance(log_context, RequestLogContext):
        payload = {
            "request_log_id": log_context.request_log_id,
            "route_template": log_context.route_template,
            "validation_error_count": len(error.errors()),
        }
        LOGGER.warning(
            "fundamental_validation_error %s",
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            extra=payload,
        )
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
    sec_acquisition: SecAcquisitionUseCase | None = None,
    identity_resolution: SecIdentityResolutionUseCase | None = None,
    quote_providers: tuple[QuoteSourceProviderPort, ...] | None = None,
    macro_providers: tuple[MacroSeriesProviderPort, ...] | None = None,
    reference_providers: tuple[MarketReferenceProviderPort, ...] | None = None,
    source_use_policy: SourceUsePolicyV1 | None = None,
    statement_originals: OriginalPreparation | None = None,
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
                models=(*executable_model_specs(), *expansion_model_specs()),
                policies=(*initial_policy_records(), *expansion_policy_records()),
            )
    metrics = OperationalMetrics()
    limiter = RateLimiter(runtime_config.rate_limit_per_minute)
    diagnostic_sink = ValuationDiagnosticSink()
    application = FundamentalApplication(
        snapshot_repository=snapshot_repository,
        artifact_store=artifact_store,
        content_store=content_store,
        fact_repository=fact_repository,
        config=runtime_config,
        metrics=metrics,
        metadata_store=metadata_store,
        statement_originals=statement_originals
        or (
            sec_acquisition.original_preparation()
            if sec_acquisition is not None and sec_acquisition.capture_store is not None
            else None
        ),
        require_metadata=require_metadata,
        policy_registry=policy_registry,
        model_inventory=model_inventory,
        quote_providers=(
            default_quote_providers() if quote_providers is None else quote_providers
        ),
        macro_providers=default_macro_providers()
        if macro_providers is None
        else macro_providers,
        reference_providers=default_reference_providers()
        if reference_providers is None
        else reference_providers,
        source_use_policy=free_market_source_policy()
        if source_use_policy is None
        else source_use_policy,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if metadata_store is not None:
            try:
                metadata_store.start()
                if policy_registry is not None:
                    for model in (
                        *initial_model_specs(),
                        *expansion_model_specs(),
                        *(
                            model_inventory.advertised()
                            if model_inventory is not None
                            else ()
                        ),
                    ):
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
                LOGGER.error("fundamental_metadata_startup_failed")
        app.state.accepting_requests = True
        try:
            yield
        finally:
            app.state.accepting_requests = False
            diagnostic_sink.close()
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
    app.state.sec_acquisition = sec_acquisition
    app.state.identity_resolution = identity_resolution
    app.state.valuation_diagnostic_sink = diagnostic_sink
    sec_acquisition_limiter = RateLimiter(
        runtime_config.ingestion_rate_limit_per_minute
    )
    valuation_limiter = CapacityLimiter(1)

    async def run_valuation_operation(
        request: Request, operation: Callable[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        deadline_at = request.state.deadline
        guard_execution_deadline(deadline_at)
        trace_enabled = runtime_config.valuation_diagnostics
        trace_started = getattr(request.state, "valuation_trace_started", monotonic())
        log_context = getattr(request.state, "log_context", None)
        operation_name = getattr(
            operation,
            "__qualname__",
            getattr(operation, "__name__", type(operation).__name__),
        )
        queue_started = monotonic()
        worker_started: float | None = None
        if trace_enabled:
            _log_valuation_diagnostic(
                request=request,
                sink=diagnostic_sink,
                operation=operation_name,
                event="queue_wait_started",
                trace_started=trace_started,
                deadline_at=deadline_at,
                queue_wait_started_at=datetime.now(UTC).isoformat(),
            )

        def execute_on_worker() -> T:
            nonlocal worker_started
            worker_started = monotonic()
            if trace_enabled:
                _log_valuation_diagnostic(
                    request=request,
                    sink=diagnostic_sink,
                    operation=operation_name,
                    event="worker_acquired",
                    trace_started=trace_started,
                    deadline_at=deadline_at,
                    queue_wait_ms=round((worker_started - queue_started) * 1000, 3),
                    worker_thread_id=get_ident(),
                )
                _log_valuation_diagnostic(
                    request=request,
                    sink=diagnostic_sink,
                    operation=operation_name,
                    event="execution_started",
                    trace_started=trace_started,
                    deadline_at=deadline_at,
                    worker_thread_id=get_ident(),
                )
            try:
                with valuation_diagnostic_scope(
                    log_context if trace_enabled else None, diagnostic_sink
                ):
                    result = operation(*args, **kwargs)
            except BaseException as error:
                if trace_enabled:
                    _log_valuation_diagnostic(
                        request=request,
                        sink=diagnostic_sink,
                        operation=operation_name,
                        event="execution_failed",
                        trace_started=trace_started,
                        deadline_at=deadline_at,
                        execution_ms=round((monotonic() - worker_started) * 1000, 3),
                        error_type=type(error).__name__,
                        error_code=diagnostic_error_code(getattr(error, "code", None)),
                        worker_thread_id=get_ident(),
                    )
                raise
            if trace_enabled:
                _log_valuation_diagnostic(
                    request=request,
                    sink=diagnostic_sink,
                    operation=operation_name,
                    event="execution_finished",
                    trace_started=trace_started,
                    deadline_at=deadline_at,
                    execution_ms=round((monotonic() - worker_started) * 1000, 3),
                    worker_thread_id=get_ident(),
                )
            return result

        try:
            with fail_after((deadline_at - datetime.now(UTC)).total_seconds()) as scope:
                result = await to_thread.run_sync(
                    execute_on_worker, limiter=valuation_limiter
                )
        except TimeoutError as error:
            if not scope.cancel_called:
                raise
            if trace_enabled:
                _log_valuation_diagnostic(
                    request=request,
                    sink=diagnostic_sink,
                    operation=operation_name,
                    event="deadline_expired",
                    trace_started=trace_started,
                    deadline_at=deadline_at,
                    timeout_phase="queue_wait"
                    if worker_started is None
                    else "execution",
                    queue_wait_ms=round(
                        ((worker_started or monotonic()) - queue_started) * 1000, 3
                    ),
                    execution_ms=(
                        round((monotonic() - worker_started) * 1000, 3)
                        if worker_started is not None
                        else None
                    ),
                )
            raise ServiceError(
                "REQUEST_DEADLINE_EXCEEDED",
                "request deadline expired while waiting for valuation execution",
                status_code=408,
                retryable=True,
            ) from error
        guard_execution_deadline(deadline_at)
        return result

    def release_actor(
        request: Request, allowed_organizations: frozenset[str]
    ) -> tuple[str, str]:
        context = request.state.context
        actor_id = context.principal.subject_id
        organization_id = context.principal.organization_id
        if (
            not isinstance(actor_id, str)
            or not actor_id
            or not isinstance(organization_id, str)
            or not organization_id
            or organization_id not in allowed_organizations
        ):
            metrics.increment("data_release_authorization_failures_total")
            raise ServiceError(
                "DATA_RELEASE_FORBIDDEN",
                "the organization is not authorized for this release operation",
                status_code=403,
                retryable=False,
            )
        return actor_id, organization_id

    @app.middleware("http")
    async def operations_boundary(request: Request, call_next):
        started = monotonic()
        try:
            request.state.log_context = create_request_log_context(request)
        except Exception:
            request.state.log_context = None
        request.state.correlation_id = correlation_id(request)
        request.state.valuation_trace_started = started
        trace_enabled = (
            runtime_config.valuation_diagnostics
            and request.url.path.startswith("/v1/valuation/")
        )
        request.state.trace_valuation_response = trace_enabled
        status_code = 500
        response: Response | None = None
        try:
            guard_body_size(request, runtime_config)
            if request.url.path.startswith("/v1/"):
                context, _ = await authorize_operation(request, runtime_config)
                if trace_enabled:
                    _log_valuation_diagnostic(
                        request=request,
                        sink=diagnostic_sink,
                        operation=None,
                        event="request_admitted",
                        trace_started=started,
                        deadline_at=getattr(request.state, "deadline", None),
                    )
                if not limiter.allow(context.principal.subject_id):
                    metrics.increment("rate_limited_total")
                    raise ServiceError(
                        "request_rate_limited",
                        "request rate exceeds the synchronous service budget",
                        status_code=429,
                        retryable=True,
                    )
                sec_acquisition_paths = {
                    "/v1/data/ingestions",
                    "/v1/identity/resolve",
                }
                if request.url.path in sec_acquisition_paths and not (
                    sec_acquisition_limiter.allow(
                        context.principal.organization_id or "unscoped"
                    )
                ):
                    is_identity_resolution = request.url.path == "/v1/identity/resolve"
                    raise ServiceError(
                        "IDENTITY_RESOLUTION_RATE_LIMITED"
                        if is_identity_resolution
                        else "INGESTION_RATE_LIMITED",
                        "organization SEC identity resolution quota is exhausted"
                        if is_identity_resolution
                        else "organization SEC ingestion quota is exhausted",
                        status_code=429,
                        retryable=True,
                        retry_after_ms=60_000,
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
            log_context = getattr(request.state, "log_context", None)
            if isinstance(log_context, RequestLogContext):
                response.headers[REQUEST_LOG_ID_HEADER] = log_context.request_log_id
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
            response = error_response(request, error)
            return response
        except Exception:  # pragma: no cover - final redacted safety net
            status_code = 500
            response = error_response(
                request,
                ServiceError(
                    "internal_failure",
                    "internal service failure",
                    status_code=500,
                    retryable=False,
                ),
            )
            return response
        finally:
            if trace_enabled:
                _log_valuation_diagnostic(
                    request=request,
                    sink=diagnostic_sink,
                    operation=None,
                    event="response_emitted",
                    trace_started=started,
                    deadline_at=getattr(request.state, "deadline", None),
                    status_code=status_code,
                    **getattr(request.state, "valuation_response_metadata", {}),
                )
            log_context = getattr(request.state, "log_context", None)
            if isinstance(log_context, RequestLogContext):
                payload = {
                    "request_log_id": log_context.request_log_id,
                    "route_template": log_context.route_template,
                    "status_code": status_code,
                    "elapsed_ms": round((monotonic() - started) * 1000, 3),
                }
                LOGGER.info(
                    "fundamental_request %s",
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    extra=payload,
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
        return _validation_error(request, error)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request, error: RequestValidationError
    ):
        return _validation_error(request, error)

    @app.get("/livez")
    async def livez() -> dict[str, str]:
        return {"contract_version": INTERNAL_CONTRACT_VERSION, "status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        return readiness_response(
            ready=application.ready,
            capabilities={
                "identity_resolution_configured": isinstance(
                    app.state.identity_resolution, SecIdentityResolutionUseCase
                )
            },
        )

    @app.get("/metrics")
    async def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain")

    @app.get("/v1/data/snapshots/{snapshot_id}", response_model=None)
    async def get_snapshot(request: Request, snapshot_id: str) -> JSONResponse:
        return success_response(request, application.snapshot(snapshot_id))

    @app.post(
        "/v1/data/annual-statements",
        response_model=TypedFundamentalResponseEnvelopeV1[
            AnnualStatementsReadResponseV1
        ],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": "#/components/schemas/FundamentalAnnualStatementsRequestEnvelopeV1"
                        }
                    }
                },
            }
        },
    )
    async def get_annual_statements(request: Request) -> JSONResponse:
        value = decode_input(request, AnnualStatementsReadRequestV1)
        result = await run_valuation_operation(
            request,
            application.read_annual_statements,
            value,
            deadline_at=request.state.deadline,
        )
        return success_response(request, result)

    @app.get(
        "/v1/data/facts",
        response_model=TypedFundamentalResponseEnvelopeV1[FactsReadResponseV1],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/FundamentalFactsRequestEnvelopeV1"
                            )
                        }
                    }
                },
            }
        },
    )
    async def get_facts(request: Request) -> JSONResponse:
        value = decode_input(request, FactsReadRequestV1)
        return success_response(request, application.read_facts(value))

    @app.post(
        "/v1/valuation/evidence/facts",
        response_model=TypedFundamentalResponseEnvelopeV1[
            ValuationEvidenceReadResponseV1
        ],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/"
                                "FundamentalValuationEvidenceRequestEnvelopeV1"
                            )
                        }
                    }
                },
            }
        },
    )
    async def read_valuation_evidence(request: Request) -> JSONResponse:
        value = decode_input(request, ValuationEvidenceReadRequestV1)
        return success_response(request, application.read_valuation_evidence(value))

    @app.post(
        "/v1/valuation/prepare",
        response_model=TypedFundamentalResponseEnvelopeV1[
            AutomaticValuationPreparationV1
        ],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/"
                                "FundamentalValuationPreparationRequestEnvelopeV1"
                            )
                        }
                    }
                },
            }
        },
    )
    async def prepare_valuation(request: Request) -> JSONResponse:
        value = decode_input(request, ValuationEvidenceReadRequestV1)
        result = await run_valuation_operation(
            request,
            application.prepare_valuation,
            value,
            deadline_at=request.state.deadline,
        )
        return success_response(request, result)

    @app.post(
        "/v1/valuation/prepare/override",
        response_model=TypedFundamentalResponseEnvelopeV1[
            AutomaticValuationPreparationV1
        ],
    )
    async def override_prepared_valuation(request: Request) -> JSONResponse:
        value = decode_input(request, ManualValuationOverrideRequestV1)
        result = await run_valuation_operation(
            request,
            application.apply_manual_override,
            value,
            revision_actor=RevisionActor(
                subject_id=request.state.context.principal.subject_id,
                organization_id=request.state.context.principal.organization_id,
            ),
            deadline_at=request.state.deadline,
        )
        return success_response(request, result)

    @app.post(
        "/v1/valuation/forward-evidence/review",
        response_model=TypedFundamentalResponseEnvelopeV1[
            ForwardEvidenceReviewResponseV1
        ],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/"
                                "FundamentalForwardEvidenceReviewRequestEnvelopeV1"
                            )
                        }
                    }
                },
            }
        },
    )
    async def review_forward_evidence_route(request: Request) -> JSONResponse:
        value = decode_input(request, ForwardEvidenceReviewRequestV1)
        result = await run_valuation_operation(
            request,
            application.review_forward_evidence,
            value,
            revision_actor=RevisionActor(
                subject_id=request.state.context.principal.subject_id,
                organization_id=request.state.context.principal.organization_id,
            ),
            deadline_at=request.state.deadline,
        )
        return success_response(request, result)

    @app.get(
        "/v1/policies/{policy_id}",
        response_model=TypedFundamentalResponseEnvelopeV1[PolicyRecordV1],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/"
                                "FundamentalPolicyLookupRequestEnvelopeV1"
                            )
                        }
                    }
                },
            }
        },
    )
    async def get_policy(request: Request, policy_id: str) -> JSONResponse:
        decode_input(request, EmptyOperationInputV1)
        return success_response(request, application.policy(policy_id))

    @app.post("/v1/data/snapshots/resolve", response_model=None)
    async def resolve_snapshot(request: Request) -> JSONResponse:
        value = decode_input(request, SnapshotResolutionRequestV1)
        return success_response(request, application.resolve_snapshot(value))

    @app.post(
        "/v1/identity/resolve",
        response_model=TypedFundamentalResponseEnvelopeV1[IdentityResolutionV1],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": "#/components/schemas/"
                            "FundamentalIdentityResolutionRequestEnvelopeV1"
                        }
                    }
                },
            }
        },
    )
    async def resolve_identity(request: Request) -> JSONResponse:
        use_case = app.state.identity_resolution
        if not isinstance(use_case, SecIdentityResolutionUseCase):
            raise ServiceError(
                "IDENTITY_RESOLUTION_UNAVAILABLE",
                "SEC identity resolution is not configured for this deployment",
                status_code=503,
                retryable=True,
            )
        value = decode_input(request, IdentityResolutionRequestV1)
        context = request.state.context
        result = await run_in_threadpool(
            use_case.execute,
            value,
            caller_principal=context.principal.subject_id,
            organization_id=context.principal.organization_id,
            correlation_id=context.correlation_id,
            deadline_at=request.state.deadline,
        )
        return success_response(request, result)

    @app.post(
        "/v1/data/releases/candidates",
        response_model=TypedFundamentalResponseEnvelopeV1[
            DataReleaseCandidateReceiptV1
        ],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/"
                                "FundamentalDataReleaseCandidateRequestEnvelopeV1"
                            )
                        }
                    }
                },
            }
        },
    )
    async def publish_data_release_candidate(request: Request) -> JSONResponse:
        release_actor(request, runtime_config.release_publish_authorized_organizations)
        value = decode_input(request, DataReleaseCandidatePublishRequestV1)
        receipt = application.publish_data_release_candidate(
            value.manifest, value.verification
        )
        metrics.increment("data_release_candidate_publish_total")
        return success_response(request, receipt)

    @app.get(
        "/v1/data/releases/{profile_id}",
        response_model=TypedFundamentalResponseEnvelopeV1[
            ActiveDataReleaseWithManifestV1
        ],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/"
                                "FundamentalDataReleaseLookupRequestEnvelopeV1"
                            )
                        }
                    }
                },
            }
        },
    )
    async def get_active_data_release(
        request: Request, profile_id: str
    ) -> JSONResponse:
        decode_input(request, EmptyOperationInputV1)
        result = application.active_data_release(profile_id)
        return success_response(request, result)

    def change_data_release(
        request: Request,
        profile_id: str,
        operation: Literal["activate", "rollback"],
    ) -> JSONResponse:
        actor_id, organization_id = release_actor(
            request, runtime_config.release_activation_authorized_organizations
        )
        value = decode_input(request, DataReleaseActivationRequestV1)
        if value.operation != operation:
            raise ServiceError(
                "DATA_RELEASE_OPERATION_MISMATCH",
                f"{operation} route requires a {operation} operation",
                status_code=422,
                retryable=False,
            )
        result = application.change_active_data_release(
            profile_id,
            value,
            actor_id=actor_id,
            organization_id=organization_id,
            correlation_id=request.state.correlation_id,
        )
        metric_name = (
            "data_release_activation_total"
            if operation == "activate"
            else "data_release_rollback_total"
        )
        metrics.increment(metric_name)
        return success_response(request, result)

    @app.post(
        "/v1/data/releases/{profile_id}/activate",
        response_model=TypedFundamentalResponseEnvelopeV1[
            ActiveDataReleaseWithManifestV1
        ],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/"
                                "FundamentalDataReleaseActivationRequestEnvelopeV1"
                            )
                        }
                    }
                },
            }
        },
    )
    async def activate_data_release(request: Request, profile_id: str) -> JSONResponse:
        return change_data_release(request, profile_id, "activate")

    @app.post(
        "/v1/data/releases/{profile_id}/rollback",
        response_model=TypedFundamentalResponseEnvelopeV1[
            ActiveDataReleaseWithManifestV1
        ],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/"
                                "FundamentalDataReleaseActivationRequestEnvelopeV1"
                            )
                        }
                    }
                },
            }
        },
    )
    async def rollback_data_release(request: Request, profile_id: str) -> JSONResponse:
        return change_data_release(request, profile_id, "rollback")

    @app.post(
        "/v1/data/ingestions",
        response_model=TypedFundamentalResponseEnvelopeV1[SecIngestionResponseV1],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": "#/components/schemas/"
                            "FundamentalIngestionRequestEnvelopeV1"
                        }
                    }
                },
            }
        },
    )
    async def ingest_sec_data(request: Request) -> JSONResponse:
        use_case = app.state.sec_acquisition
        if not isinstance(use_case, SecAcquisitionUseCase):
            raise ServiceError(
                "SOURCE_ACQUISITION_UNAVAILABLE",
                "SEC ingestion is not configured for this service deployment",
                status_code=503,
                retryable=True,
            )
        value = decode_input(request, SecIngestionRequestV1)
        context = request.state.context
        result = await run_in_threadpool(
            use_case.execute,
            value,
            caller_principal=context.principal.subject_id,
            organization_id=context.principal.organization_id,
            correlation_id=context.correlation_id,
            deadline_at=request.state.deadline,
        )
        return success_response(request, result)

    @app.get("/v1/artifacts/{artifact_id}", response_model=None)
    async def get_artifact(request: Request, artifact_id: str) -> JSONResponse:
        record = await run_valuation_operation(
            request,
            application.artifact,
            artifact_id,
            revision_actor=RevisionActor(
                subject_id=request.state.context.principal.subject_id,
                organization_id=request.state.context.principal.organization_id,
            ),
            deadline_at=request.state.deadline,
        )
        return success_response(request, record)

    @app.get("/v1/artifacts/{artifact_id}/content")
    async def get_artifact_content(request: Request, artifact_id: str) -> Response:
        record, content = await run_valuation_operation(
            request,
            application.artifact_content,
            artifact_id,
            revision_actor=RevisionActor(
                subject_id=request.state.context.principal.subject_id,
                organization_id=request.state.context.principal.organization_id,
            ),
            deadline_at=request.state.deadline,
        )
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
            uncertainty_value = UncertaintyRequestV1.model_validate_json(
                json.dumps(normalize_uncertainty_payload(raw_input))
            )
            return success_response(
                request, application.validate_uncertainty(uncertainty_value)
            )
        value = decode_input(request, ValuationInputV1)
        return success_response(request, application.validate_valuation(value))

    @app.post(
        "/v1/valuation/validate-with-policy",
        response_model=None,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/"
                                "FundamentalPolicyValidationRequestEnvelopeV1"
                            )
                        }
                    }
                },
            }
        },
    )
    async def validate_with_policy(request: Request) -> JSONResponse:
        value = decode_input(request, PolicyValuationInputV1)
        return success_response(request, application.validate_with_policy(value))

    @app.post(
        "/v1/valuation/calculate",
        response_model=TypedFundamentalResponseEnvelopeV1[
            CalculationArtifactV1 | UncertaintyReportV1
        ],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/"
                                "FundamentalCalculationRequestEnvelopeV1"
                            )
                        }
                    }
                },
            }
        },
    )
    async def calculate_valuation(request: Request) -> JSONResponse:
        value = decode_input(request, ValuationInputV1)
        result = await run_valuation_operation(
            request,
            application.calculate_valuation,
            value,
            revision_actor=RevisionActor(
                subject_id=request.state.context.principal.subject_id,
                organization_id=request.state.context.principal.organization_id,
            ),
            correlation_id=request.state.correlation_id,
            deadline_at=request.state.deadline,
        )
        return success_response(request, result)

    @app.post(
        "/v1/valuation/calculate-with-policy",
        response_model=TypedFundamentalResponseEnvelopeV1[
            CalculationArtifactV1 | UncertaintyReportV1
        ],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/"
                                "FundamentalPolicyCalculationRequestEnvelopeV1"
                            )
                        }
                    }
                },
            }
        },
    )
    async def calculate_with_policy(request: Request) -> JSONResponse:
        value = decode_input(request, PolicyValuationInputV1)
        result = await run_valuation_operation(
            request,
            application.calculate_with_policy,
            value,
            revision_actor=RevisionActor(
                subject_id=request.state.context.principal.subject_id,
                organization_id=request.state.context.principal.organization_id,
            ),
            correlation_id=request.state.correlation_id,
            deadline_at=request.state.deadline,
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
        result = await run_valuation_operation(
            request,
            application.uncertainty_valuation,
            value,
            deadline_at=request.state.deadline,
        )
        return success_response(request, result)

    base_openapi = app.openapi

    def openapi_with_typed_internal_envelopes():
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = base_openapi()
        request_models = (
            (
                "FundamentalCalculationRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[ValuationInputV1],
            ),
            (
                "FundamentalFactsRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[FactsReadRequestV1],
            ),
            (
                "FundamentalValuationEvidenceRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[ValuationEvidenceReadRequestV1],
            ),
            (
                "FundamentalValuationPreparationRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[ValuationEvidenceReadRequestV1],
            ),
            (
                "FundamentalManualValuationOverrideRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[ManualValuationOverrideRequestV1],
            ),
            (
                "FundamentalForwardEvidenceReviewRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[ForwardEvidenceReviewRequestV1],
            ),
            (
                "FundamentalPolicyLookupRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[EmptyOperationInputV1],
            ),
            (
                "FundamentalPolicyCalculationRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[PolicyValuationInputV1],
            ),
            (
                "FundamentalPolicyValidationRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[PolicyValuationInputV1],
            ),
            (
                "FundamentalIngestionRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[SecIngestionRequestV1],
            ),
            (
                "FundamentalAnnualStatementsRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[AnnualStatementsReadRequestV1],
            ),
            (
                "FundamentalIdentityResolutionRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[IdentityResolutionRequestV1],
            ),
            (
                "FundamentalDataReleaseCandidateRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[DataReleaseCandidatePublishRequestV1],
            ),
            (
                "FundamentalDataReleaseLookupRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[EmptyOperationInputV1],
            ),
            (
                "FundamentalDataReleaseActivationRequestEnvelopeV1",
                TypedFundamentalRequestEnvelopeV1[DataReleaseActivationRequestV1],
            ),
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for name, model in request_models:
            model_schema = model.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
            definitions = model_schema.pop("$defs", {})
            components.update(definitions)
            components[name] = model_schema
        app.openapi_schema = schema
        return schema

    setattr(app, "openapi", openapi_with_typed_internal_envelopes)
    return app


def create_runtime_app() -> FastAPI:
    """Build production with PostgreSQL metadata and a content-only volume."""

    config = OperationsConfig.from_env()
    source_use_policy = load_runtime_source_use_policy()
    root_value = os.getenv("FUNDAMENTAL_SERVICE_DATA_ROOT")
    database_url = os.getenv("FUNDAMENTAL_SERVICE_DATABASE_URL")
    if not root_value or not database_url:
        return create_app(
            config=config,
            require_metadata=True,
            source_use_policy=source_use_policy,
        )
    root = Path(root_value)
    data_release_trust_roots_file = os.getenv(
        "FUNDAMENTAL_DATA_RELEASE_TRUST_ROOTS_FILE"
    )
    metadata_store = PostgresMetadataStore(
        database_url,
        auto_migrate=os.getenv("FUNDAMENTAL_SERVICE_AUTO_MIGRATE", "0") == "1",
        data_release_trust_roots=(
            DataReleaseTrustRootsV1.from_file(Path(data_release_trust_roots_file))
            if data_release_trust_roots_file
            else None
        ),
    )
    trust_roots_value = os.getenv("FUNDAMENTAL_MODEL_TRUST_ROOTS_FILE")
    model_inventory = ModelInventory.from_deployment_file(
        (*dated_model_specs(), *expansion_model_specs()),
        Path(trust_roots_value) if trust_roots_value else None,
    )
    model_release_path = os.getenv("FUNDAMENTAL_MODEL_RELEASE_DEPLOYMENT_FILE")
    promoted_models = (
        load_model_release_deployment(Path(model_release_path), model_inventory)
        if model_release_path
        else ()
    )
    content_store = PostgresContentStore(root / "content", metadata_store)
    taxonomy_cache_dir = os.getenv("FUNDAMENTAL_SEC_TAXONOMY_CACHE_DIR")
    taxonomy_manifest_id = os.getenv("FUNDAMENTAL_SEC_TAXONOMY_MANIFEST_ID")
    taxonomy_version = os.getenv("FUNDAMENTAL_SEC_TAXONOMY_VERSION")
    taxonomy_cache_sha256 = os.getenv("FUNDAMENTAL_SEC_TAXONOMY_CACHE_SHA256")
    edgar_plugin_dir = os.getenv("FUNDAMENTAL_SEC_EDGAR_PLUGIN_DIR")
    xule_plugin_dir = os.getenv("FUNDAMENTAL_SEC_XULE_PLUGIN_DIR")
    dqc_ruleset_path = os.getenv("FUNDAMENTAL_SEC_DQC_RULESET_PATH")
    edgar_plugin_sha256 = os.getenv("FUNDAMENTAL_SEC_EDGAR_PLUGIN_SHA256")
    xule_plugin_sha256 = os.getenv("FUNDAMENTAL_SEC_XULE_PLUGIN_SHA256")
    dqc_ruleset_sha256 = os.getenv("FUNDAMENTAL_SEC_DQC_RULESET_SHA256")
    supported_filing_years = parse_supported_filing_years(
        os.getenv("FUNDAMENTAL_SEC_SUPPORTED_FILING_YEARS")
    )
    supported_filing_forms = parse_supported_filing_forms(
        os.getenv("FUNDAMENTAL_SEC_SUPPORTED_FILING_FORMS")
    )
    sec_acquisition = build_runtime_sec_acquisition(
        metadata=metadata_store,
        content_store=content_store,
        snapshot_repository=PostgresSnapshotRepository(metadata_store),
        fact_repository=PostgresCanonicalFactRepository(metadata_store),
        service_token=config.service_token,
        user_agent=os.getenv("FUNDAMENTAL_SEC_USER_AGENT"),
        taxonomy_cache_dir=taxonomy_cache_dir,
        taxonomy_manifest_id=taxonomy_manifest_id,
        taxonomy_version=taxonomy_version,
        taxonomy_cache_sha256=taxonomy_cache_sha256,
        edgar_plugin_dir=edgar_plugin_dir,
        xule_plugin_dir=xule_plugin_dir,
        dqc_ruleset_path=dqc_ruleset_path,
        edgar_plugin_sha256=edgar_plugin_sha256,
        xule_plugin_sha256=xule_plugin_sha256,
        dqc_ruleset_sha256=dqc_ruleset_sha256,
        dqc_ruleset_catalog_path=os.getenv("FUNDAMENTAL_SEC_DQC_RULESET_CATALOG_PATH")
        or None,
        dqc_v18_ruleset_catalog_path=os.getenv(
            "FUNDAMENTAL_SEC_DQC_V18_RULESET_CATALOG_PATH"
        )
        or None,
        historical_dqc_dir=os.getenv("FUNDAMENTAL_SEC_HISTORICAL_DQC_DIR") or None,
        historical_dqc_sha256=os.getenv("FUNDAMENTAL_SEC_HISTORICAL_DQC_SHA256")
        or None,
        supported_filing_years=supported_filing_years,
        supported_filing_forms=supported_filing_forms,
        authorized_organizations=config.ingestion_authorized_organizations,
    )
    identity_resolution = build_runtime_sec_identity_resolution(
        metadata=metadata_store,
        content_store=content_store,
        user_agent=os.getenv("FUNDAMENTAL_SEC_USER_AGENT"),
        authorized_organizations=config.ingestion_authorized_organizations,
    )
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
            models=promoted_models,
            model_repository=MetadataModelRepository(metadata_store),
            repository=MetadataPolicyRepository(metadata_store),
        ),
        sec_acquisition=sec_acquisition,
        identity_resolution=identity_resolution,
        source_use_policy=source_use_policy,
    )


app = create_runtime_app()
