import asyncio
import hmac
import os
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal

import uvicorn
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl import (
    warmup_dependency_matcher,
    warmup_forward_looking_filter,
)
from src.agents.intent.entrypoint import InterruptValue
from src.agents.news.infrastructure.content_fetch import close_shared_async_client
from src.agents.technical.subdomains.decision_observability import (
    TechnicalCalibrationObservationBuildResultModel,
    TechnicalDecisionObservabilityRuntimeService,
    TechnicalMonitoringAggregateModel,
    TechnicalMonitoringEventDetailModel,
    TechnicalMonitoringRowModel,
    build_default_technical_decision_observability_runtime_service,
    build_monitoring_query_scope,
    build_technical_calibration_observation_build_result_model,
    build_technical_monitoring_aggregate_model,
    build_technical_monitoring_event_detail_model,
    build_technical_monitoring_row_model,
)
from src.auth.entrypoint import auth_router, get_ownership_service
from src.auth.interface.contracts import Principal as AuthPrincipal
from src.auth.interface.dependencies import (
    require_current_user,
    require_current_user_mutation,
)
from src.infrastructure.database import init_db
from src.infrastructure.llm.litellm_admin import (
    LiteLLMAdminClient,
    LiteLLMAdminError,
    ManagedKey,
    validate_model_id,
)
from src.infrastructure.llm.openrouter_key_test import (
    OpenRouterKeyTestError,
    test_openrouter_key,
)
from src.infrastructure.llm.openrouter_models import (
    OpenRouterModelsError,
    list_free_models,
    validate_free_model,
)
from src.infrastructure.llm.provider import close_llm_provider
from src.infrastructure.sentiment import get_finbert_analyzer
from src.interface.artifacts.artifact_api_models import (
    ArtifactApiResponse,
    validate_artifact_api_response,
)
from src.interface.auth.local_admin import (
    Principal as LocalPrincipal,
)
from src.interface.auth.local_admin import (
    issue_local_admin_session,
    require_local_admin,
    validate_local_admin_request,
)
from src.interface.auth.local_admin import (
    settings as local_admin_settings,
)
from src.interface.events.adapters import adapt_langgraph_event, create_interrupt_event
from src.interface.events.protocol import AgentEvent
from src.interface.events.schemas import AgentOutputArtifact
from src.runtime.workspace_runtime_projection import (
    WorkspaceRuntimeActivityRecord,
    WorkspaceRuntimeActivitySegmentRecord,
    WorkspaceRuntimeProjectionService,
    build_default_workspace_runtime_projection_repository,
    derive_active_agent_id,
    derive_recent_activity,
)
from src.services.artifact_manager import artifact_manager
from src.services.history import history_service
from src.services.llm_settings import get_selected_model, set_selected_model
from src.shared.kernel.tools.logger import (
    bind_log_context,
    clear_log_context,
    get_logger,
    log_context,
)
from src.shared.kernel.types import InterruptResumePayload, JSONObject
from src.shared.llm.context import reset_provider_principal, set_provider_principal
from src.shared.llm.contracts import ProviderPrincipal
from src.shared.llm.routes import DEFAULT_MODEL_ALIAS, user_route_alias
from src.workflow.graph import get_graph

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager for the FastAPI application.
    Constructs and compiles the graph once at startup.
    """
    logger.info("🚀 [Lifespan] Initializing application resources...")
    # Initialize DB
    await init_db()
    selected_model = await get_selected_model()
    try:
        gateway_admin = get_litellm_admin_client()
        await gateway_admin.update_model(selected_model)
    except (HTTPException, LiteLLMAdminError) as exc:
        logger.warning("LLM model synchronization skipped: %s", str(exc))
    finally:
        if "gateway_admin" in locals():
            await gateway_admin.close()

    # Initialize Graph
    logger.info("🚀 [Lifespan] Building workflow graph...")
    graph = await get_graph()
    app.state.graph = graph

    # Build Agent Identity Lookup (Zero Config)
    app.state.agent_lookup = build_agent_lookup(graph)
    logger.info(f"🔎 [Lifespan] Discovered {len(app.state.agent_lookup)} agent nodes.")

    runtime_projection_repo = build_default_workspace_runtime_projection_repository()
    app.state.runtime_projection = WorkspaceRuntimeProjectionService(
        runtime_projection_repo
    )

    warmup_enabled = os.getenv("NEWS_FINBERT_WARMUP", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if warmup_enabled:
        logger.info("🚀 [Lifespan] Warming up FinBERT model cache...")
        warmup_started = time.perf_counter()
        analyzer = get_finbert_analyzer()
        try:
            available = await asyncio.to_thread(analyzer.is_available)
            elapsed_ms = int((time.perf_counter() - warmup_started) * 1000)
            if available:
                logger.info(
                    "✅ [Lifespan] FinBERT warmup completed in %d ms.",
                    elapsed_ms,
                )
            else:
                logger.warning(
                    "⚠️ [Lifespan] FinBERT warmup skipped: %s",
                    analyzer.load_error or "unknown error",
                )
        except Exception as exc:
            logger.warning("⚠️ [Lifespan] FinBERT warmup failed: %s", str(exc))

    fls_warmup_enabled = os.getenv("SEC_TEXT_FLS_WARMUP", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if fls_warmup_enabled:
        logger.info("🚀 [Lifespan] Warming up FLS filter model cache...")
        try:
            warmup_result = await asyncio.to_thread(warmup_forward_looking_filter)
            if bool(warmup_result.get("loaded")):
                logger.info(
                    "✅ [Lifespan] FLS warmup completed: load=%sms inference=%sms batches=%s",
                    warmup_result.get("model_load_ms", 0.0),
                    warmup_result.get("inference_ms", 0.0),
                    warmup_result.get("batches", 0),
                )
            else:
                logger.warning(
                    "⚠️ [Lifespan] FLS warmup skipped: %s",
                    warmup_result.get("error", "unknown error"),
                )
        except Exception as exc:
            logger.warning("⚠️ [Lifespan] FLS warmup failed: %s", str(exc))

    dependency_warmup_enabled = os.getenv(
        "SEC_TEXT_DEPENDENCY_WARMUP", "1"
    ).strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if dependency_warmup_enabled:
        logger.info("🚀 [Lifespan] Warming up dependency matcher cache...")
        try:
            dep_result = await asyncio.to_thread(warmup_dependency_matcher)
            if bool(dep_result.get("loaded")):
                logger.info(
                    "✅ [Lifespan] Dependency matcher warmup completed: model=%s",
                    dep_result.get("model", "unknown"),
                )
            else:
                logger.warning(
                    "⚠️ [Lifespan] Dependency matcher warmup skipped: %s",
                    dep_result.get("error", "unknown error"),
                )
        except Exception as exc:
            logger.warning(
                "⚠️ [Lifespan] Dependency matcher warmup failed: %s", str(exc)
            )

    logger.info("✅ [Lifespan] Initialization complete.")
    try:
        yield
    finally:
        await close_llm_provider()
        await close_shared_async_client()
        logger.info("🛑 [Lifespan] Shutting down...")


app = FastAPI(
    title="Neuro-Symbolic Valuation Engine API",
    version="2.0",
    description="Pure FastAPI implementation for FinGraph Valuation Agent (Path B)",
    lifespan=lifespan,
)

app.include_router(auth_router)


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    if request.url.path == "/api/settings/openrouter-keys" and request.method == "POST":
        detail = [
            {key: error[key] for key in ("loc", "msg", "type") if key in error}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": detail})
    return await request_validation_exception_handler(request, exc)


def _cors_origins() -> list[str]:
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if configured:
        return [
            origin.strip().rstrip("/")
            for origin in configured.split(",")
            if origin.strip()
        ]
    return [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:3001",
        "http://localhost:3001",
    ]


# Browser credentials require an explicit origin allowlist.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Operations"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["Operations"])
async def ready(request: Request) -> dict[str, str]:
    if not hasattr(request.app.state, "graph"):
        raise HTTPException(status_code=503, detail="application is still starting")
    return {"status": "ready"}


class OpenRouterKeyCreateRequest(BaseModel):
    label: str = Field(default="OpenRouter key", min_length=1, max_length=80)
    api_key: SecretStr = Field(min_length=20, max_length=500)


class OpenRouterKeyResponse(BaseModel):
    id: str
    label: str
    suffix: str
    fingerprint: str
    created_at: str | None = None


class OpenRouterKeyTestResponse(BaseModel):
    id: str
    passed: bool
    status: Literal["healthy", "invalid_key", "rate_limited", "unavailable"]


class LlmModelOptionResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    context_length: int | None = None


class LlmSettingsResponse(BaseModel):
    selected_model: str
    default_model: str
    models: list[LlmModelOptionResponse]


class LlmSettingsUpdateRequest(BaseModel):
    selected_model: str = Field(min_length=1, max_length=200)


@app.post(
    "/api/auth/local-admin/session",
    response_model=LocalPrincipal,
    tags=["Authentication"],
)
async def create_local_admin_session(
    request: Request, response: Response
) -> LocalPrincipal:
    """Create the temporary loopback-only admin session used in development."""
    validate_local_admin_request(request)
    return issue_local_admin_session(response)


@app.delete("/api/auth/local-admin/session", status_code=204, tags=["Authentication"])
async def delete_local_admin_session(request: Request, response: Response) -> None:
    validate_local_admin_request(request)
    response.delete_cookie(key="local_admin_session", path="/")


def require_llm_admin_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> LocalPrincipal:
    if local_admin_settings().enabled:
        try:
            return require_local_admin(request)
        except HTTPException as local_error:
            if local_error.status_code not in {401, 404}:
                raise

    expected = os.getenv("LLM_PROVIDER_ADMIN_TOKEN", "").strip()
    if not expected:
        if local_admin_settings().enabled:
            raise HTTPException(
                status_code=401, detail="local admin session is required"
            )
        raise HTTPException(
            status_code=503, detail="LLM provider administration is disabled"
        )
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=403, detail="LLM provider administration is not authorized"
        )
    return LocalPrincipal(
        subject="configured-admin", role="platform_admin", auth_type="bearer"
    )


SettingsPrincipal = AuthPrincipal | LocalPrincipal


async def require_settings_principal(request: Request) -> SettingsPrincipal:
    try:
        return await require_current_user(request)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        return require_llm_admin_token(
            request, authorization=request.headers.get("Authorization")
        )


async def require_settings_mutation(request: Request) -> SettingsPrincipal:
    try:
        return await require_current_user_mutation(request)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        return require_llm_admin_token(
            request, authorization=request.headers.get("Authorization")
        )


def _is_platform_admin(principal: SettingsPrincipal) -> bool:
    return principal.role == "platform_admin"


def _user_id(principal: SettingsPrincipal) -> str:
    return (
        principal.user_id if isinstance(principal, AuthPrincipal) else principal.subject
    )


def get_litellm_admin_client() -> LiteLLMAdminClient:
    base_url = os.getenv("LLM_GATEWAY_BASE_URL", "http://localhost:4000").strip()
    token = os.getenv("LLM_GATEWAY_API_KEY", "").strip()
    if not base_url or not token:
        raise HTTPException(
            status_code=503, detail="LLM gateway administration is unavailable"
        )
    openrouter_headers = {
        "X-Title": os.getenv("OPENROUTER_X_TITLE", "Value Investment Agent")
    }
    referer = os.getenv("OPENROUTER_HTTP_REFERER", "").strip()
    if referer:
        openrouter_headers["HTTP-Referer"] = referer
    return LiteLLMAdminClient(
        base_url=base_url,
        admin_token=token,
        openrouter_headers=openrouter_headers,
    )


def _managed_key_response(key: ManagedKey) -> OpenRouterKeyResponse:
    return OpenRouterKeyResponse(
        id=key.id,
        label=key.label,
        suffix=key.suffix,
        fingerprint=key.fingerprint,
        created_at=key.created_at,
    )


llm_keys_router = APIRouter(
    prefix="/api/settings/openrouter-keys",
    tags=["LLM provider settings"],
)


@llm_keys_router.get("", response_model=list[OpenRouterKeyResponse])
async def list_openrouter_keys(
    principal: SettingsPrincipal = Depends(require_settings_principal),
    client: LiteLLMAdminClient = Depends(get_litellm_admin_client),
) -> list[OpenRouterKeyResponse]:
    try:
        owned_ids = (
            None
            if _is_platform_admin(principal)
            else await get_ownership_service().owned_ids(
                user_id=_user_id(principal), resource_type="provider_key"
            )
        )
        return [
            _managed_key_response(key)
            for key in await client.list_managed()
            if owned_ids is None or key.id in owned_ids
        ]
    except LiteLLMAdminError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@llm_keys_router.post("", response_model=OpenRouterKeyResponse, status_code=201)
async def add_openrouter_key(
    request: OpenRouterKeyCreateRequest,
    principal: SettingsPrincipal = Depends(require_settings_mutation),
    client: LiteLLMAdminClient = Depends(get_litellm_admin_client),
) -> OpenRouterKeyResponse:
    raw_key = request.api_key.get_secret_value()
    try:
        await test_openrouter_key(raw_key)
    except OpenRouterKeyTestError as exc:
        status = str(exc)
        code = 429 if status == "rate_limited" else 502
        if status == "invalid_key":
            code = 400
        raise HTTPException(status_code=code, detail=status) from exc
    try:
        selected_model = await get_selected_model()
        managed = await client.add_key(
            key=raw_key,
            label=request.label,
            model=selected_model,
            model_name=(
                DEFAULT_MODEL_ALIAS
                if _is_platform_admin(principal)
                else user_route_alias(_user_id(principal))
            ),
        )
        claimed = _is_platform_admin(principal) or await get_ownership_service().claim(
            user_id=_user_id(principal),
            resource_type="provider_key",
            resource_id=managed.id,
        )
        if not claimed:
            await client.delete_key(managed.id)
            raise HTTPException(status_code=409, detail="managed key is already owned")
        return _managed_key_response(managed)
    except LiteLLMAdminError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@llm_keys_router.post("/{key_id}/test", response_model=OpenRouterKeyTestResponse)
async def test_openrouter_key_route(
    key_id: str,
    principal: SettingsPrincipal = Depends(require_settings_mutation),
    client: LiteLLMAdminClient = Depends(get_litellm_admin_client),
) -> OpenRouterKeyTestResponse:
    try:
        key_id = validate_model_id(key_id)
        if not _is_platform_admin(principal) and not await get_ownership_service().owns(
            user_id=_user_id(principal),
            resource_type="provider_key",
            resource_id=key_id,
        ):
            raise HTTPException(status_code=404, detail="managed key was not found")
        await client.test_key(key_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid managed key id") from exc
    except LiteLLMAdminError as exc:
        reason = str(exc)
        if reason == "not_found":
            raise HTTPException(
                status_code=404, detail="managed key was not found"
            ) from exc
        status = (
            reason
            if reason in {"invalid_key", "rate_limited", "unavailable"}
            else "unavailable"
        )
        return OpenRouterKeyTestResponse(id=key_id, passed=False, status=status)
    return OpenRouterKeyTestResponse(id=key_id, passed=True, status="healthy")


@llm_keys_router.delete("/{key_id}", status_code=204)
async def delete_openrouter_key(
    key_id: str,
    principal: SettingsPrincipal = Depends(require_settings_mutation),
    client: LiteLLMAdminClient = Depends(get_litellm_admin_client),
) -> None:
    try:
        key_id = validate_model_id(key_id)
        if not _is_platform_admin(principal) and not await get_ownership_service().owns(
            user_id=_user_id(principal),
            resource_type="provider_key",
            resource_id=key_id,
        ):
            raise HTTPException(status_code=404, detail="managed key was not found")
        await client.delete_key(key_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid managed key id") from exc
    except LiteLLMAdminError as exc:
        if str(exc) == "managed key was not found":
            raise HTTPException(
                status_code=404, detail="managed key was not found"
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


app.include_router(llm_keys_router)


llm_settings_router = APIRouter(
    prefix="/api/settings/llm",
    tags=["LLM provider settings"],
)


async def _llm_settings_response() -> LlmSettingsResponse:
    try:
        models = await list_free_models()
    except OpenRouterModelsError as exc:
        raise HTTPException(
            status_code=502, detail="OpenRouter model catalogue is unavailable"
        ) from exc
    selected = await get_selected_model()
    if not any(model.id == selected for model in models):
        selected = "openrouter/free"
    return LlmSettingsResponse(
        selected_model=selected,
        default_model="openrouter/free",
        models=[
            LlmModelOptionResponse(
                id=model.id,
                name=model.name,
                description=model.description,
                context_length=model.context_length,
            )
            for model in models
        ],
    )


@llm_settings_router.get("", response_model=LlmSettingsResponse)
async def read_llm_settings(
    _principal: SettingsPrincipal = Depends(require_settings_principal),
) -> LlmSettingsResponse:
    return await _llm_settings_response()


@llm_settings_router.put("", response_model=LlmSettingsResponse)
async def update_llm_settings(
    request: LlmSettingsUpdateRequest,
    principal: SettingsPrincipal = Depends(require_settings_mutation),
) -> LlmSettingsResponse:
    try:
        valid = await validate_free_model(request.selected_model)
    except OpenRouterModelsError as exc:
        raise HTTPException(
            status_code=502, detail="OpenRouter model catalogue is unavailable"
        ) from exc
    if not valid:
        raise HTTPException(
            status_code=400, detail="selected model is not a free OpenRouter model"
        )
    client = get_litellm_admin_client()
    try:
        await client.update_model(request.selected_model)
    except LiteLLMAdminError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await client.close()
    await set_selected_model(request.selected_model, updated_by=principal.subject)
    return await _llm_settings_response()


app.include_router(llm_settings_router)


@lru_cache
def get_observability_runtime() -> TechnicalDecisionObservabilityRuntimeService:
    return build_default_technical_decision_observability_runtime_service()


observability_router = APIRouter(prefix="/api/observability", tags=["Observability"])


def _build_observability_scope(
    *,
    tickers: list[str],
    agent_sources: list[str],
    timeframes: list[str],
    horizons: list[str],
    logic_versions: list[str],
    directions: list[str],
    run_types: list[str],
    reliability_levels: list[str],
    event_time_start: datetime | None,
    event_time_end: datetime | None,
    resolved_time_start: datetime | None,
    resolved_time_end: datetime | None,
    labeling_method_version: str,
    limit: int,
):
    return build_monitoring_query_scope(
        tickers=tickers,
        agent_sources=agent_sources,
        timeframes=timeframes,
        horizons=horizons,
        logic_versions=logic_versions,
        directions=directions,
        run_types=run_types,
        reliability_levels=reliability_levels,
        event_time_start=event_time_start,
        event_time_end=event_time_end,
        resolved_time_start=resolved_time_start,
        resolved_time_end=resolved_time_end,
        labeling_method_version=labeling_method_version,
        limit=limit,
    )


@observability_router.get(
    "/monitoring/aggregates", response_model=list[TechnicalMonitoringAggregateModel]
)
async def get_monitoring_aggregates(
    tickers: list[str] = Query(default=[]),
    agent_sources: list[str] = Query(default=[]),
    timeframes: list[str] = Query(default=[]),
    horizons: list[str] = Query(default=[]),
    logic_versions: list[str] = Query(default=[]),
    directions: list[str] = Query(default=[]),
    run_types: list[str] = Query(default=[]),
    reliability_levels: list[str] = Query(default=[]),
    event_time_start: datetime | None = Query(default=None),
    event_time_end: datetime | None = Query(default=None),
    resolved_time_start: datetime | None = Query(default=None),
    resolved_time_end: datetime | None = Query(default=None),
    labeling_method_version: str = Query(default="technical_outcome_labeling.v1"),
    limit: int = Query(default=200),
    runtime: TechnicalDecisionObservabilityRuntimeService = Depends(
        get_observability_runtime
    ),
):
    scope = _build_observability_scope(
        tickers=tickers,
        agent_sources=agent_sources,
        timeframes=timeframes,
        horizons=horizons,
        logic_versions=logic_versions,
        directions=directions,
        run_types=run_types,
        reliability_levels=reliability_levels,
        event_time_start=event_time_start,
        event_time_end=event_time_end,
        resolved_time_start=resolved_time_start,
        resolved_time_end=resolved_time_end,
        labeling_method_version=labeling_method_version,
        limit=limit,
    )
    aggregates = await runtime.load_monitoring_aggregates(scope=scope)
    return [build_technical_monitoring_aggregate_model(agg) for agg in aggregates]


@observability_router.get(
    "/monitoring/rows", response_model=list[TechnicalMonitoringRowModel]
)
async def get_monitoring_rows(
    tickers: list[str] = Query(default=[]),
    agent_sources: list[str] = Query(default=[]),
    timeframes: list[str] = Query(default=[]),
    horizons: list[str] = Query(default=[]),
    logic_versions: list[str] = Query(default=[]),
    directions: list[str] = Query(default=[]),
    run_types: list[str] = Query(default=[]),
    reliability_levels: list[str] = Query(default=[]),
    event_time_start: datetime | None = Query(default=None),
    event_time_end: datetime | None = Query(default=None),
    resolved_time_start: datetime | None = Query(default=None),
    resolved_time_end: datetime | None = Query(default=None),
    labeling_method_version: str = Query(default="technical_outcome_labeling.v1"),
    limit: int = Query(default=200),
    runtime: TechnicalDecisionObservabilityRuntimeService = Depends(
        get_observability_runtime
    ),
):
    scope = _build_observability_scope(
        tickers=tickers,
        agent_sources=agent_sources,
        timeframes=timeframes,
        horizons=horizons,
        logic_versions=logic_versions,
        directions=directions,
        run_types=run_types,
        reliability_levels=reliability_levels,
        event_time_start=event_time_start,
        event_time_end=event_time_end,
        resolved_time_start=resolved_time_start,
        resolved_time_end=resolved_time_end,
        labeling_method_version=labeling_method_version,
        limit=limit,
    )
    rows = await runtime.load_monitoring_rows(scope=scope)
    return [build_technical_monitoring_row_model(row) for row in rows]


@observability_router.get(
    "/monitoring/events/{event_id}",
    response_model=TechnicalMonitoringEventDetailModel,
)
async def get_monitoring_event_detail(
    event_id: str,
    labeling_method_version: str = Query(default="technical_outcome_labeling.v1"),
    runtime: TechnicalDecisionObservabilityRuntimeService = Depends(
        get_observability_runtime
    ),
):
    detail = await runtime.load_monitoring_event_detail(
        event_id=event_id,
        labeling_method_version=labeling_method_version,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Observability event not found")
    return build_technical_monitoring_event_detail_model(detail)


@observability_router.get(
    "/calibration/direction-readiness",
    response_model=TechnicalCalibrationObservationBuildResultModel,
)
async def get_direction_calibration_readiness(
    tickers: list[str] = Query(default=[]),
    agent_sources: list[str] = Query(default=[]),
    timeframes: list[str] = Query(default=[]),
    horizons: list[str] = Query(default=[]),
    logic_versions: list[str] = Query(default=[]),
    directions: list[str] = Query(default=[]),
    run_types: list[str] = Query(default=[]),
    reliability_levels: list[str] = Query(default=[]),
    event_time_start: datetime | None = Query(default=None),
    event_time_end: datetime | None = Query(default=None),
    resolved_time_start: datetime | None = Query(default=None),
    resolved_time_end: datetime | None = Query(default=None),
    labeling_method_version: str = Query(default="technical_outcome_labeling.v1"),
    limit: int = Query(default=200),
    include_observations: bool = Query(default=False),
    runtime: TechnicalDecisionObservabilityRuntimeService = Depends(
        get_observability_runtime
    ),
):
    scope = _build_observability_scope(
        tickers=tickers,
        agent_sources=agent_sources,
        timeframes=timeframes,
        horizons=horizons,
        logic_versions=logic_versions,
        directions=directions,
        run_types=run_types,
        reliability_levels=reliability_levels,
        event_time_start=event_time_start,
        event_time_end=event_time_end,
        resolved_time_start=resolved_time_start,
        resolved_time_end=resolved_time_end,
        labeling_method_version=labeling_method_version,
        limit=limit,
    )
    result = await runtime.load_direction_calibration_observations(scope=scope)
    return build_technical_calibration_observation_build_result_model(
        result, include_observations=include_observations
    )


app.include_router(observability_router)


class RequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    message: str | None = None
    resume_payload: InterruptResumePayload | None = None


class MessageResponse(BaseModel):
    id: str
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    type: str = "text"
    data: dict[str, object] | list[object] | str | int | float | bool | None = None
    created_at: str | None = None
    agentId: str | None = None


class StatusHistoryEntryResponse(BaseModel):
    id: str
    node: str
    agentId: str
    status: str
    timestamp: datetime


class ActivitySegmentResponse(BaseModel):
    id: str
    agentId: str
    node: str
    runId: str
    status: str
    started_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None
    is_current: bool


class RuntimeCursorResponse(BaseModel):
    last_seq_id: int
    updated_at: datetime | None = None


class RunStatusResponse(BaseModel):
    run_id: str
    status: str
    started_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None


class ActivityTimelineEntryResponse(BaseModel):
    event_id: str
    seq_id: int
    run_id: str | None
    agent_id: str
    node: str | None
    event_type: str
    status: str | None
    payload: dict[str, object]
    created_at: datetime


class ThreadStateResponse(BaseModel):
    thread_id: str
    messages: list[MessageResponse]
    interrupts: list[InterruptValue]
    resolved_ticker: str | None = None
    status: str | None = None
    next: list[str] | None = None
    is_running: bool
    agent_statuses: dict[str, str]
    node_statuses: dict[str, str]
    agent_outputs: dict[str, AgentOutputArtifact]
    last_seq_id: int
    cursor: RuntimeCursorResponse | None = None
    current_node: str | None = None
    current_status: str | None = None
    status_history: list[StatusHistoryEntryResponse] = []
    activity_timeline: list[ActivityTimelineEntryResponse] = []
    active_agent_id: str | None = None
    run: RunStatusResponse | None = None


class AgentStatusesResponse(BaseModel):
    agent_statuses: dict[str, str]
    node_statuses: dict[str, str]
    current_node: str | None = None
    agent_outputs: dict[str, AgentOutputArtifact]


class StreamStartResponse(BaseModel):
    status: Literal["started", "running"]
    thread_id: str
    run_id: str


async def _require_thread_owner(*, user_id: str, thread_id: str) -> None:
    owned = await get_ownership_service().owns(
        user_id=user_id, resource_type="thread", resource_id=thread_id
    )
    if not owned:
        raise HTTPException(status_code=404, detail="thread was not found")


# Track active tasks, running queues, and sequence counters
active_tasks: dict[str, asyncio.Task] = {}
running_queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
thread_sequences: dict[str, int] = defaultdict(lambda: 1)


@app.middleware("http")
async def attach_request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    bind_log_context(request_id=request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        clear_log_context()


def build_agent_lookup(graph: CompiledStateGraph) -> dict[str, str]:
    """
    Recursively traverse the graph to build a node_name -> agent_id map.
    This enables Zero Config architecture by discovering identity at runtime.
    """
    lookup = {}

    def traverse(g: CompiledStateGraph) -> None:
        for name, node in g.nodes.items():
            # 1. Map current node
            metadata = getattr(node, "metadata", None)
            if isinstance(metadata, dict):
                agent_id = metadata.get("agent_id")
                if isinstance(agent_id, str):
                    lookup[name] = agent_id

            # 2. Recurse into subgraphs
            runnable = getattr(node, "bound", None)
            if isinstance(runnable, CompiledStateGraph):
                traverse(runnable)

    traverse(graph)
    return lookup


def _normalize_statuses(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(
            f"Invalid node_statuses type, expected mapping got {type(value)!r}"
        )
    normalized: dict[str, str] = {}
    for key, status in value.items():
        if not isinstance(key, str) or not isinstance(status, str):
            raise TypeError("node_statuses must be a mapping[str, str]")
        normalized[key] = status
    return normalized


def _message_agent_id(value: object) -> str | None:
    if not isinstance(value, AIMessage | HumanMessage):
        return None
    direct_agent_id = value.additional_kwargs.get("agentId")
    if isinstance(direct_agent_id, str):
        return direct_agent_id
    snake_agent_id = value.additional_kwargs.get("agent_id")
    if isinstance(snake_agent_id, str):
        return snake_agent_id
    return None


def _build_activity_timeline(
    records: list[WorkspaceRuntimeActivityRecord],
) -> list[ActivityTimelineEntryResponse]:
    timeline: list[ActivityTimelineEntryResponse] = []
    for record in records:
        if not isinstance(record, object):
            continue
        timeline.append(
            ActivityTimelineEntryResponse(
                event_id=record.event_id,
                seq_id=record.seq_id,
                run_id=record.run_id,
                agent_id=record.agent_id,
                node=record.node,
                event_type=record.event_type,
                status=record.status,
                payload=record.payload,
                created_at=record.created_at,
            )
        )
    return timeline


def _build_status_history_from_activity(
    records: list[WorkspaceRuntimeActivityRecord],
) -> list[StatusHistoryEntryResponse]:
    history: list[StatusHistoryEntryResponse] = []
    ordered = sorted(records, key=lambda record: record.created_at)
    for record in ordered:
        if record.event_type != "agent.status":
            continue
        if record.status is None:
            continue
        node = record.node if record.node else record.agent_id
        history.append(
            StatusHistoryEntryResponse(
                id=f"status_{record.event_id}",
                node=node,
                agentId=record.agent_id,
                status=record.status,
                timestamp=record.created_at,
            )
        )
    return history[-20:]


def _build_activity_segment_entries(
    records: list[WorkspaceRuntimeActivitySegmentRecord],
    *,
    mark_current: bool,
) -> list[ActivitySegmentResponse]:
    ordered = sorted(records, key=lambda record: record.updated_at, reverse=True)
    segments: list[ActivitySegmentResponse] = []
    for idx, record in enumerate(ordered):
        segments.append(
            ActivitySegmentResponse(
                id=record.segment_id,
                agentId=record.agent_id,
                node=record.node,
                runId=record.run_id,
                status=record.status,
                started_at=record.started_at,
                updated_at=record.updated_at,
                ended_at=record.ended_at,
                is_current=mark_current and idx == 0,
            )
        )
    return segments


def _derive_current_status(
    *,
    is_running: bool,
    status_history: list[StatusHistoryEntryResponse],
    has_interrupts: bool,
) -> str | None:
    if status_history:
        return status_history[-1].status
    if has_interrupts:
        return "attention"
    if is_running:
        return "running"
    return None


def _format_sse_event(event: AgentEvent) -> str:
    payload = event.model_dump_json()
    return f"id: {event.seq_id}\nevent: {event.type}\ndata: {payload}\n\n"


def _parse_after_seq(
    *,
    after_seq: int | None,
    last_event_id: str | None,
) -> int | None:
    if after_seq is not None:
        return after_seq
    if last_event_id is None:
        return None
    try:
        return int(last_event_id)
    except ValueError:
        return None


def _build_event_from_activity_record(
    record: WorkspaceRuntimeActivityRecord,
) -> AgentEvent:
    payload = record.payload if isinstance(record.payload, Mapping) else {}
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    metadata = (
        payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    )
    return AgentEvent(
        id=record.event_id,
        timestamp=record.created_at,
        thread_id=record.thread_id,
        run_id=record.run_id or "",
        seq_id=record.seq_id,
        type=record.event_type,
        source=record.agent_id,
        data=dict(data),
        metadata=dict(metadata),
    )


async def _resolve_next_seq_id(
    *,
    thread_id: str,
    runtime_projection: WorkspaceRuntimeProjectionService | None,
) -> int:
    fallback_seq_id = thread_sequences.get(thread_id, 1)
    if runtime_projection is None:
        return fallback_seq_id
    return await runtime_projection.resolve_next_seq_id(
        thread_id=thread_id,
        fallback_seq_id=fallback_seq_id,
    )


async def event_generator(
    thread_id: str,
    input_data: Command | dict[str, object],
    config: dict[str, dict[str, str]],
    graph: CompiledStateGraph,
    *,
    run_id: str,
    principal: AuthPrincipal,
    agent_lookup: dict[str, str] | None = None,
    runtime_projection: WorkspaceRuntimeProjectionService | None = None,
):
    """
    Core event generator that transforms LangGraph events into standardized AgentEvents.
    """
    agent_lookup = agent_lookup or {}
    seq_counter = thread_sequences[thread_id]
    logger.info(
        "server_event_generator_started thread_id=%s seq=%d", thread_id, seq_counter
    )
    provider_context_token = set_provider_principal(
        ProviderPrincipal(user_id=principal.user_id)
    )

    with log_context(
        thread_id=thread_id,
        run_id=run_id,
        node="server.event_generator",
    ):
        try:
            # State for token batching
            batch_state = {"buffer": [], "last_event": None}

            async def persist_event(agent_event: AgentEvent) -> None:
                if runtime_projection is None:
                    return
                try:
                    await runtime_projection.record_event(agent_event)
                except Exception as exc:
                    logger.warning(
                        "workspace_runtime_projection_write_failed seq=%d type=%s error=%s",
                        agent_event.seq_id,
                        agent_event.type,
                        str(exc),
                    )

            async def flush_deltas():
                nonlocal seq_counter
                last_delta = batch_state["last_event"]
                delta_buffer = batch_state["buffer"]

                if not last_delta or not delta_buffer:
                    return

                # Combine all buffered contents
                combined_content = "".join(delta_buffer)
                # Update the last delta event with combined content
                last_delta.data["content"] = combined_content
                last_delta.seq_id = seq_counter

                await persist_event(last_delta)

                msg = _format_sse_event(last_delta)
                # Silence high-frequency logs by using DEBUG level
                logger.debug(
                    "server_dispatch_token_batch count=%d source=%s",
                    len(delta_buffer),
                    last_delta.source,
                )

                for q in running_queues[thread_id][:]:
                    await q.put(msg)

                seq_counter += 1
                thread_sequences[thread_id] = seq_counter
                batch_state["buffer"].clear()
                batch_state["last_event"] = None

            running_event = AgentEvent(
                thread_id=thread_id,
                run_id=run_id,
                seq_id=seq_counter,
                type="lifecycle.status",
                source="System",
                data={"status": "running"},
            )
            await persist_event(running_event)
            running_msg = _format_sse_event(running_event)
            logger.info("server_dispatch_lifecycle_running seq=%d", seq_counter)

            for q in running_queues[thread_id][:]:
                await q.put(running_msg)

            seq_counter += 1
            thread_sequences[thread_id] = seq_counter

            # 1. Stream refined events using adapter
            async for event in graph.astream_events(
                input_data, config=config, version="v2"
            ):
                # Handle token batching logic.
                if event["event"] == "on_chat_model_stream":
                    agent_events = adapt_langgraph_event(
                        event, thread_id, seq_counter, run_id
                    )

                    for agent_event in agent_events:
                        if agent_event.type != "content.delta":
                            continue

                        # Flush if source changed or buffer reached threshold.
                        last_event = batch_state["last_event"]
                        if last_event and (
                            last_event.source != agent_event.source
                            or len(batch_state["buffer"]) >= 25
                        ):
                            await flush_deltas()

                        if not batch_state["last_event"]:
                            batch_state["last_event"] = agent_event

                        batch_state["buffer"].append(
                            agent_event.data.get("content", "")
                        )
                    continue

                # Non-stream chunk: flush pending deltas first.
                await flush_deltas()

                # Then adapt current event with the fresh seq_counter.
                agent_events = adapt_langgraph_event(
                    event, thread_id, seq_counter, run_id
                )
                for agent_event in agent_events:
                    await persist_event(agent_event)

                    msg = _format_sse_event(agent_event)
                    logger.info(
                        "server_dispatch_event seq=%d type=%s source=%s",
                        seq_counter,
                        agent_event.type,
                        agent_event.source,
                    )

                    for q in running_queues[thread_id][:]:
                        await q.put(msg)

                    seq_counter += 1
                    thread_sequences[thread_id] = seq_counter

            # Final flush after stream ends.
            await flush_deltas()

            # 2. Check for interrupts after graph pauses.
            snapshot = await graph.aget_state(config)
            if snapshot.next:
                for task in snapshot.tasks:
                    if not task.interrupts:
                        continue
                    for interrupt_item in task.interrupts:
                        agent_id = agent_lookup.get(task.name)
                        source = agent_id or task.name

                        agent_event = create_interrupt_event(
                            interrupt_item.value,
                            thread_id,
                            seq_counter,
                            run_id,
                            source=source,
                        )
                        await persist_event(agent_event)
                        msg = _format_sse_event(agent_event)
                        logger.info(
                            "server_dispatch_interrupt seq=%d source=%s",
                            seq_counter,
                            source,
                        )

                        for q in running_queues[thread_id][:]:
                            await q.put(msg)
                        seq_counter += 1
                        thread_sequences[thread_id] = seq_counter

                        attention_event = AgentEvent(
                            thread_id=thread_id,
                            run_id=run_id,
                            seq_id=seq_counter,
                            type="agent.status",
                            source=source,
                            data={"status": "attention", "node": task.name},
                        )
                        await persist_event(attention_event)
                        attention_msg = _format_sse_event(attention_event)
                        logger.info(
                            "server_dispatch_attention seq=%d source=%s",
                            seq_counter,
                            source,
                        )
                        for q in running_queues[thread_id][:]:
                            await q.put(attention_msg)
                        seq_counter += 1
                        thread_sequences[thread_id] = seq_counter

                        lifecycle_attention = AgentEvent(
                            thread_id=thread_id,
                            run_id=run_id,
                            seq_id=seq_counter,
                            type="agent.lifecycle",
                            source=source,
                            data={"status": "attention"},
                        )
                        await persist_event(lifecycle_attention)
                        lifecycle_msg = _format_sse_event(lifecycle_attention)
                        logger.info(
                            "server_dispatch_lifecycle_attention seq=%d source=%s",
                            seq_counter,
                            source,
                        )
                        for q in running_queues[thread_id][:]:
                            await q.put(lifecycle_msg)
                        seq_counter += 1
                        thread_sequences[thread_id] = seq_counter
            else:
                # 3. Workflow completed successfully.
                done_event = AgentEvent(
                    thread_id=thread_id,
                    run_id=run_id,
                    seq_id=seq_counter,
                    type="lifecycle.status",
                    source="System",
                    data={"status": "done"},
                )
                await persist_event(done_event)
                msg = _format_sse_event(done_event)
                logger.info("server_dispatch_done seq=%d", seq_counter)

                for q in running_queues[thread_id][:]:
                    await q.put(msg)

                seq_counter += 1
                thread_sequences[thread_id] = seq_counter

        except Exception as exc:
            logger.error(
                "server_event_generator_error thread_id=%s error=%s",
                thread_id,
                str(exc),
                exc_info=True,
            )
            error_event = AgentEvent(
                thread_id=thread_id,
                run_id=run_id,
                seq_id=seq_counter,
                type="error",
                source="System",
                data={"message": str(exc)},
            )
            await persist_event(error_event)
            msg = _format_sse_event(error_event)
            for q in running_queues[thread_id][:]:
                await q.put(msg)
        finally:
            reset_provider_principal(provider_context_token)
            # Signal EOF to all queues.
            for q in running_queues[thread_id][:]:
                await q.put(None)

            # Cleanup.
            if thread_id in active_tasks:
                del active_tasks[thread_id]
            if thread_id in running_queues:
                del running_queues[thread_id]
            logger.info("server_task_finished thread_id=%s", thread_id)


@app.get("/history/{thread_id}", response_model=list[MessageResponse])
async def get_history(
    thread_id: str,
    limit: int = 20,
    before: str | None = None,
    principal: AuthPrincipal = Depends(require_current_user),
):
    """Retrieve persistent history with cursor pagination."""
    try:
        await _require_thread_owner(user_id=principal.user_id, thread_id=thread_id)
        before_dt = None
        if before:
            from datetime import datetime

            before_dt = datetime.fromisoformat(before)

        messages = await history_service.get_history(thread_id, limit, before_dt)
        return [m.to_dict() for m in messages]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/thread/{thread_id}", response_model=ThreadStateResponse)
async def get_thread_history(
    request: Request,
    thread_id: str,
    principal: AuthPrincipal = Depends(require_current_user),
):
    """Retrieve history and job status."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
        await _require_thread_owner(user_id=principal.user_id, thread_id=thread_id)
        graph = request.app.state.graph
        snapshot = await graph.aget_state(config)

        messages: list[MessageResponse] = []
        for m in snapshot.values.get("messages", []):
            if isinstance(m, AIMessage):
                role: Literal["assistant", "user", "system", "tool"] = "assistant"
            elif isinstance(m, HumanMessage):
                role = "user"
            else:
                role = "system"
            msg_type_raw = m.additional_kwargs.get("type", "text")
            msg_type = msg_type_raw if isinstance(msg_type_raw, str) else "text"
            messages.append(
                MessageResponse(
                    id=getattr(m, "id", None) or f"msg_{id(m)}",
                    role=role,
                    content=str(m.content),
                    type=msg_type,
                    data=m.additional_kwargs.get("data"),
                    agentId=_message_agent_id(m),
                )
            )

        current_interrupts: list[InterruptValue] = []
        for task in snapshot.tasks:
            if task.interrupts:
                for i in task.interrupts:
                    try:
                        val = InterruptValue.model_validate(i.value)
                        current_interrupts.append(val)
                    except Exception as exc:
                        logger.warning(
                            f"Skipping invalid interrupt payload in thread {thread_id}: {exc}"
                        )
                        continue

        # Helper to safely extract nested context
        def get_context(name: str) -> JSONObject:
            val = snapshot.values.get(name)
            if val is None:
                return {}
            if not isinstance(val, dict):
                raise TypeError(
                    f"Invalid state context '{name}', expected dict got {type(val)!r}"
                )
            return val

        fundamental = get_context("fundamental_analysis")

        # Dynamic Agent Output Discovery (Standardization Phase 1)
        # Use Mapper instead of raw loop
        from src.interface.events.mappers import NodeOutputMapper

        agent_outputs = NodeOutputMapper.map_all_outputs(snapshot.values)
        current_node_raw = snapshot.values.get("current_node")
        if current_node_raw is not None and not isinstance(current_node_raw, str):
            raise TypeError(
                f"Invalid current_node type, expected str|None got {type(current_node_raw)!r}"
            )
        runtime_projection = getattr(request.app.state, "runtime_projection", None)
        activity_records: list[WorkspaceRuntimeActivityRecord] = []
        cursor = None
        if runtime_projection is None:
            raise RuntimeError("runtime_projection is required for thread hydration")
        activity_records = list(
            await runtime_projection.fetch_recent_activity(
                thread_id=thread_id,
                limit=50,
            )
        )
        cursor = await runtime_projection.fetch_cursor(thread_id=thread_id)
        node_statuses = await runtime_projection.fetch_latest_statuses(
            thread_id=thread_id
        )
        agent_statuses = await runtime_projection.fetch_latest_lifecycle_statuses(
            thread_id=thread_id
        )
        run_status_record = await runtime_projection.fetch_run_status(
            thread_id=thread_id
        )

        activity_ordered = sorted(
            activity_records, key=lambda record: record.created_at
        )
        recent_activity = list(derive_recent_activity(activity_records, limit=20))
        activity_timeline = _build_activity_timeline(recent_activity)
        status_history = _build_status_history_from_activity(activity_ordered)
        active_agent_id = derive_active_agent_id(activity_ordered)
        last_seq_id = cursor.last_seq_id if cursor else 0
        cursor_payload = (
            RuntimeCursorResponse(
                last_seq_id=cursor.last_seq_id,
                updated_at=cursor.updated_at,
            )
            if cursor
            else None
        )
        run_payload = (
            RunStatusResponse(
                run_id=run_status_record.run_id,
                status=run_status_record.status,
                started_at=run_status_record.started_at,
                updated_at=run_status_record.updated_at,
                ended_at=run_status_record.ended_at,
            )
            if run_status_record
            else None
        )

        is_running = thread_id in active_tasks
        current_status = _derive_current_status(
            is_running=is_running,
            status_history=status_history,
            has_interrupts=bool(current_interrupts),
        )

        return ThreadStateResponse(
            thread_id=thread_id,
            messages=messages,
            interrupts=current_interrupts,
            resolved_ticker=fundamental.get("resolved_ticker"),
            status=fundamental.get("status"),
            next=snapshot.next,
            is_running=is_running,
            agent_statuses=agent_statuses,
            node_statuses=node_statuses,
            agent_outputs=agent_outputs,
            last_seq_id=last_seq_id,
            cursor=cursor_payload,
            current_node=current_node_raw,
            current_status=current_status,
            status_history=status_history,
            activity_timeline=activity_timeline,
            active_agent_id=active_agent_id,
            run=run_payload,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [Server] get_thread_history failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/thread/{thread_id}/agents", response_model=AgentStatusesResponse)
async def get_agent_statuses(
    request: Request,
    thread_id: str,
    principal: AuthPrincipal = Depends(require_current_user),
):
    """Retrieve node statuses and financial reports for the dashboard."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
        await _require_thread_owner(user_id=principal.user_id, thread_id=thread_id)
        graph = request.app.state.graph
        snapshot = await graph.aget_state(config)
        from src.interface.events.mappers import NodeOutputMapper

        agent_outputs = NodeOutputMapper.map_all_outputs(snapshot.values)
        current_node = snapshot.values.get("current_node")
        if current_node is not None and not isinstance(current_node, str):
            raise TypeError(
                f"Invalid current_node type, expected str|None got {type(current_node)!r}"
            )
        runtime_projection = getattr(request.app.state, "runtime_projection", None)
        if runtime_projection is None:
            raise RuntimeError("runtime_projection is required for agent statuses")
        node_statuses = await runtime_projection.fetch_latest_statuses(
            thread_id=thread_id
        )
        agent_statuses = await runtime_projection.fetch_latest_lifecycle_statuses(
            thread_id=thread_id
        )
        return AgentStatusesResponse(
            agent_statuses=agent_statuses,
            node_statuses=node_statuses,
            current_node=current_node,
            agent_outputs=agent_outputs,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/thread/{thread_id}/activity", response_model=list[ActivitySegmentResponse])
async def get_agent_activity(
    request: Request,
    thread_id: str,
    principal: AuthPrincipal = Depends(require_current_user),
    agent_id: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=200),
    before_updated_at: datetime | None = Query(None),
):
    """Retrieve per-agent activity segments with cursor pagination."""
    try:
        await _require_thread_owner(user_id=principal.user_id, thread_id=thread_id)
        runtime_projection = getattr(request.app.state, "runtime_projection", None)
        if runtime_projection is None:
            raise RuntimeError("runtime_projection is required for agent activity")
        normalized_before_updated_at = before_updated_at
        if before_updated_at is not None and before_updated_at.tzinfo is not None:
            normalized_before_updated_at = before_updated_at.astimezone(
                timezone.utc
            ).replace(tzinfo=None)
        records = list(
            await runtime_projection.fetch_activity_segments(
                thread_id=thread_id,
                agent_id=agent_id,
                limit=limit,
                before_updated_at=normalized_before_updated_at,
            )
        )
        return _build_activity_segment_entries(
            records, mark_current=before_updated_at is None
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/artifacts/{artifact_id}", response_model=ArtifactApiResponse)
async def get_artifact(
    artifact_id: str,
    principal: AuthPrincipal = Depends(require_current_user),
):
    """Retrieve artifact data with HTTP caching."""
    from fastapi.responses import JSONResponse

    envelope = await artifact_manager.get_artifact_envelope(artifact_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact = await artifact_manager.get_artifact(artifact_id)
    if artifact is None or artifact.thread_id is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    await _require_thread_owner(user_id=principal.user_id, thread_id=artifact.thread_id)

    validated = validate_artifact_api_response(
        envelope.model_dump(mode="json"),
        context=f"artifact {artifact_id}",
    )

    return JSONResponse(
        content=validated.model_dump(mode="json"),
        headers={
            "Cache-Control": "public, max-age=3600",
            "ETag": f'"{artifact_id}"',
        },
    )


@app.get("/stream/{thread_id}")
async def attach_stream(
    request: Request,
    thread_id: str,
    _principal: AuthPrincipal = Depends(require_current_user),
    after_seq: int | None = Query(default=None, ge=0),
):
    """Attach to an existing background job's event stream."""

    async def sse_adapter():
        # 1. Create a queue for the new listener
        q = asyncio.Queue()
        running_queues[thread_id].append(q)

        runtime_projection = getattr(request.app.state, "runtime_projection", None)
        last_event_id = request.headers.get("Last-Event-ID")
        replay_after = _parse_after_seq(
            after_seq=after_seq,
            last_event_id=last_event_id,
        )

        if runtime_projection is not None and replay_after is not None:
            try:
                backlog = await runtime_projection.fetch_activity_since(
                    thread_id=thread_id,
                    after_seq=replay_after,
                    limit=200,
                )
                if backlog:
                    logger.info(
                        "server_stream_replay thread_id=%s count=%d after_seq=%s",
                        thread_id,
                        len(backlog),
                        replay_after,
                    )
                for record in backlog:
                    yield _format_sse_event(_build_event_from_activity_record(record))
            except Exception as exc:
                logger.warning(
                    "server_stream_replay_failed thread_id=%s error=%s",
                    thread_id,
                    str(exc),
                )

        yield "retry: 10000\n\n"

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if msg is None:
                    # EOF signal
                    break
                yield msg
        finally:
            if thread_id in running_queues and q in running_queues[thread_id]:
                running_queues[thread_id].remove(q)

    return StreamingResponse(sse_adapter(), media_type="text/event-stream")


@app.post("/stream", response_model=StreamStartResponse)
async def stream_agent(
    request: Request,
    body: RequestSchema,
    principal: AuthPrincipal = Depends(require_current_user_mutation),
):
    """Start or resume a job."""
    thread_id = body.thread_id
    if not await get_ownership_service().claim(
        user_id=principal.user_id, resource_type="thread", resource_id=thread_id
    ):
        raise HTTPException(status_code=404, detail="thread was not found")
    config = {"configurable": {"thread_id": thread_id}}
    runtime_projection = getattr(request.app.state, "runtime_projection", None)

    if thread_id in active_tasks:
        if body.message or body.resume_payload:
            raise HTTPException(
                status_code=409, detail="Job already running for this thread."
            )
        existing_run = None
        if runtime_projection is not None:
            existing_run = await runtime_projection.fetch_run_status(
                thread_id=thread_id
            )
        return StreamStartResponse(
            status="running",
            thread_id=thread_id,
            run_id=existing_run.run_id if existing_run else "",
        )

    # Prepare input
    if body.message:
        if runtime_projection is not None:
            existing_run = await runtime_projection.fetch_run_status(
                thread_id=thread_id
            )
            if existing_run is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Thread already has a run. Start a new thread for a new ticker.",
                )
        run_id = str(uuid.uuid4())
        # Advance sequence from durable cursor
        thread_sequences[thread_id] = await _resolve_next_seq_id(
            thread_id=thread_id,
            runtime_projection=runtime_projection,
        )

        user_msg = HumanMessage(content=body.message)
        await history_service.save_message(thread_id, user_msg)
        input_data = {"messages": [user_msg], "user_query": body.message}
    elif body.resume_payload:
        run_id = str(uuid.uuid4())
        if runtime_projection is not None:
            existing_run = await runtime_projection.fetch_run_status(
                thread_id=thread_id
            )
            if existing_run is None:
                raise HTTPException(
                    status_code=409,
                    detail="No active run for this thread. Start a new thread.",
                )
            if existing_run.status in {"done", "error", "degraded"}:
                raise HTTPException(
                    status_code=409,
                    detail="Run already completed. Start a new thread for a new ticker.",
                )
            run_id = existing_run.run_id
        # RESUME: Keep existing sequence
        thread_sequences[thread_id] = await _resolve_next_seq_id(
            thread_id=thread_id,
            runtime_projection=runtime_projection,
        )
        input_data = Command(resume=body.resume_payload)
    else:
        raise HTTPException(
            status_code=400, detail="Either message or resume_payload is required."
        )

    # Start independent task
    task = asyncio.create_task(
        event_generator(
            thread_id,
            input_data,
            config,
            request.app.state.graph,
            run_id=run_id,
            principal=principal,
            agent_lookup=request.app.state.agent_lookup,
            runtime_projection=runtime_projection,
        )
    )
    active_tasks[thread_id] = task

    return StreamStartResponse(status="started", thread_id=thread_id, run_id=run_id)


# Removed app.on_event("startup") in favor of lifespan


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
