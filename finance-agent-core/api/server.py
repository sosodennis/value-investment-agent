import asyncio
import os
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from typing import Literal

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl import (
    warmup_dependency_matcher,
    warmup_forward_looking_filter,
)
from src.agents.news.infrastructure.content_fetch import close_shared_async_client
from src.agents.news.infrastructure.sentiment import get_finbert_analyzer
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
from src.infrastructure.database import init_db
from src.interface.artifacts.artifact_api_models import (
    ArtifactApiResponse,
    validate_artifact_api_response,
)
from src.interface.events.adapters import adapt_langgraph_event, create_interrupt_event
from src.interface.events.protocol import AgentEvent
from src.interface.events.schemas import AgentOutputArtifact
from src.services.artifact_manager import artifact_manager
from src.services.history import history_service
from src.shared.kernel.tools.logger import (
    bind_log_context,
    clear_log_context,
    get_logger,
    log_context,
)
from src.shared.kernel.types import InterruptResumePayload, JSONObject
from src.workflow.graph import get_graph
from src.workflow.interrupts import InterruptValue

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

    # Initialize Graph
    logger.info("🚀 [Lifespan] Building workflow graph...")
    graph = await get_graph()
    app.state.graph = graph

    # Build Agent Identity Lookup (Zero Config)
    app.state.agent_lookup = build_agent_lookup(graph)
    logger.info(f"🔎 [Lifespan] Discovered {len(app.state.agent_lookup)} agent nodes.")

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
    yield
    await close_shared_async_client()
    logger.info("🛑 [Lifespan] Shutting down...")


app = FastAPI(
    title="Neuro-Symbolic Valuation Engine API",
    version="2.0",
    description="Pure FastAPI implementation for FinGraph Valuation Agent (Path B)",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class ThreadStateResponse(BaseModel):
    thread_id: str
    messages: list[MessageResponse]
    interrupts: list[InterruptValue]
    resolved_ticker: str | None = None
    status: str | None = None
    next: list[str] | None = None
    is_running: bool
    node_statuses: dict[str, str]
    agent_outputs: dict[str, AgentOutputArtifact]
    last_seq_id: int
    current_node: str | None = None
    current_status: str | None = None
    status_history: list[StatusHistoryEntryResponse] = []


class AgentStatusesResponse(BaseModel):
    node_statuses: dict[str, str]
    current_node: str | None = None
    agent_outputs: dict[str, AgentOutputArtifact]


class StreamStartResponse(BaseModel):
    status: Literal["started", "running"]
    thread_id: str


# Track active tasks, event replay buffers, and sequence counters
active_tasks: dict[str, asyncio.Task] = {}
running_queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
event_replay_buffers: dict[str, list[str]] = defaultdict(list)
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


def _build_status_history(thread_id: str) -> list[StatusHistoryEntryResponse]:
    history: list[StatusHistoryEntryResponse] = []
    for raw_message in event_replay_buffers.get(thread_id, []):
        line = raw_message.strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if payload == "null":
            continue
        try:
            event = AgentEvent.model_validate_json(payload)
        except Exception:
            continue
        if event.type != "agent.status":
            continue
        status = event.data.get("status")
        if not isinstance(status, str):
            continue
        node = event.data.get("node")
        history.append(
            StatusHistoryEntryResponse(
                id=f"status_{event.id}",
                node=node if isinstance(node, str) and node else event.source,
                agentId=event.source,
                status=status,
                timestamp=event.timestamp,
            )
        )
    return history[-20:]


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


async def event_generator(
    thread_id: str,
    input_data: Command | dict[str, object],
    config: dict[str, dict[str, str]],
    graph: CompiledStateGraph,
    agent_lookup: dict[str, str] | None = None,
):
    """
    Core event generator that transforms LangGraph events into standardized AgentEvents.
    """
    agent_lookup = agent_lookup or {}
    seq_counter = thread_sequences[thread_id]
    run_id = str(uuid.uuid4())
    logger.info(
        "server_event_generator_started thread_id=%s seq=%d", thread_id, seq_counter
    )

    with log_context(
        thread_id=thread_id,
        run_id=run_id,
        node="server.event_generator",
    ):
        try:
            # State for token batching
            batch_state = {"buffer": [], "last_event": None}

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

                msg = f"data: {last_delta.model_dump_json()}\n\n"
                # Silence high-frequency logs by using DEBUG level
                logger.debug(
                    "server_dispatch_token_batch count=%d source=%s",
                    len(delta_buffer),
                    last_delta.source,
                )

                event_replay_buffers[thread_id].append(msg)
                if len(event_replay_buffers[thread_id]) > 50:
                    event_replay_buffers[thread_id].pop(0)

                for q in running_queues[thread_id][:]:
                    await q.put(msg)

                seq_counter += 1
                thread_sequences[thread_id] = seq_counter
                batch_state["buffer"].clear()
                batch_state["last_event"] = None

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
                    msg = f"data: {agent_event.model_dump_json()}\n\n"
                    logger.info(
                        "server_dispatch_event seq=%d type=%s source=%s",
                        seq_counter,
                        agent_event.type,
                        agent_event.source,
                    )

                    event_replay_buffers[thread_id].append(msg)
                    if len(event_replay_buffers[thread_id]) > 50:
                        event_replay_buffers[thread_id].pop(0)

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
                        msg = f"data: {agent_event.model_dump_json()}\n\n"
                        logger.info(
                            "server_dispatch_interrupt seq=%d source=%s",
                            seq_counter,
                            source,
                        )

                        event_replay_buffers[thread_id].append(msg)
                        for q in running_queues[thread_id][:]:
                            await q.put(msg)
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
                msg = f"data: {done_event.model_dump_json()}\n\n"
                logger.info("server_dispatch_done seq=%d", seq_counter)

                event_replay_buffers[thread_id].append(msg)
                if len(event_replay_buffers[thread_id]) > 50:
                    event_replay_buffers[thread_id].pop(0)

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
            msg = f"data: {error_event.model_dump_json()}\n\n"
            for q in running_queues[thread_id][:]:
                await q.put(msg)
        finally:
            # Signal EOF to all queues.
            for q in running_queues[thread_id][:]:
                await q.put(None)

            # Keep buffer for pending GETs.
            await asyncio.sleep(2)

            # Cleanup.
            if thread_id in active_tasks:
                del active_tasks[thread_id]
            if thread_id in running_queues:
                del running_queues[thread_id]
            if thread_id in event_replay_buffers:
                del event_replay_buffers[thread_id]
            logger.info("server_task_finished thread_id=%s", thread_id)


@app.get("/history/{thread_id}", response_model=list[MessageResponse])
async def get_history(thread_id: str, limit: int = 20, before: str | None = None):
    """Retrieve persistent history with cursor pagination."""
    try:
        before_dt = None
        if before:
            from datetime import datetime

            before_dt = datetime.fromisoformat(before)

        messages = await history_service.get_history(thread_id, limit, before_dt)
        return [m.to_dict() for m in messages]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/thread/{thread_id}", response_model=ThreadStateResponse)
async def get_thread_history(request: Request, thread_id: str):
    """Retrieve history and job status."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
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
        node_statuses = _normalize_statuses(snapshot.values.get("node_statuses"))
        last_seq_id = max(thread_sequences.get(thread_id, 1) - 1, 0)
        current_node_raw = snapshot.values.get("current_node")
        if current_node_raw is not None and not isinstance(current_node_raw, str):
            raise TypeError(
                f"Invalid current_node type, expected str|None got {type(current_node_raw)!r}"
            )
        status_history = _build_status_history(thread_id)
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
            node_statuses=node_statuses,
            agent_outputs=agent_outputs,
            last_seq_id=last_seq_id,
            current_node=current_node_raw,
            current_status=current_status,
            status_history=status_history,
        )
    except Exception as e:
        logger.error(f"❌ [Server] get_thread_history failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/thread/{thread_id}/agents", response_model=AgentStatusesResponse)
async def get_agent_statuses(request: Request, thread_id: str):
    """Retrieve node statuses and financial reports for the dashboard."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
        graph = request.app.state.graph
        snapshot = await graph.aget_state(config)
        from src.interface.events.mappers import NodeOutputMapper

        agent_outputs = NodeOutputMapper.map_all_outputs(snapshot.values)
        node_statuses = _normalize_statuses(snapshot.values.get("node_statuses"))
        current_node = snapshot.values.get("current_node")
        if current_node is not None and not isinstance(current_node, str):
            raise TypeError(
                f"Invalid current_node type, expected str|None got {type(current_node)!r}"
            )
        return AgentStatusesResponse(
            node_statuses=node_statuses,
            current_node=current_node,
            agent_outputs=agent_outputs,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/artifacts/{artifact_id}", response_model=ArtifactApiResponse)
async def get_artifact(artifact_id: str):
    """Retrieve artifact data with HTTP caching."""
    from fastapi.responses import JSONResponse

    envelope = await artifact_manager.get_artifact_envelope(artifact_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

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
async def attach_stream(thread_id: str):
    """Attach to an existing background job's event stream."""

    async def sse_adapter():
        # 1. Create a queue for the new listener
        q = asyncio.Queue()
        running_queues[thread_id].append(q)

        # 2. Replay already generated events for this thread (race condition fix)
        if thread_id in event_replay_buffers:
            logger.info(
                f"🔄 [Server] Replaying {len(event_replay_buffers[thread_id])} events for attacher on {thread_id}"
            )
            for msg in event_replay_buffers[thread_id]:
                await q.put(msg)

        try:
            while True:
                msg = await q.get()
                if msg is None:
                    # EOF signal
                    break
                yield msg
        finally:
            if thread_id in running_queues and q in running_queues[thread_id]:
                running_queues[thread_id].remove(q)

    return StreamingResponse(sse_adapter(), media_type="text/event-stream")


@app.post("/stream", response_model=StreamStartResponse)
async def stream_agent(request: Request, body: RequestSchema):
    """Start or resume a job."""
    thread_id = body.thread_id
    config = {"configurable": {"thread_id": thread_id}}

    if thread_id in active_tasks:
        if body.message or body.resume_payload:
            raise HTTPException(
                status_code=409, detail="Job already running for this thread."
            )
        return StreamStartResponse(status="running", thread_id=thread_id)

    # Prepare input
    if body.message:
        # BRAND NEW analysis: Reset sequence and clear previous event buffers
        thread_sequences[thread_id] = 1
        if thread_id in event_replay_buffers:
            event_replay_buffers[thread_id] = []

        user_msg = HumanMessage(content=body.message)
        await history_service.save_message(thread_id, user_msg)
        input_data = {"messages": [user_msg], "user_query": body.message}
    elif body.resume_payload:
        # RESUME: Keep existing sequence
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
            request.app.state.agent_lookup,
        )
    )
    active_tasks[thread_id] = task

    return StreamStartResponse(status="started", thread_id=thread_id)


# Removed app.on_event("startup") in favor of lifespan


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
