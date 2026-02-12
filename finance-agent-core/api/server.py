import asyncio
import os
import sys
import uuid
from collections import defaultdict
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from src.common.tools.logger import get_logger
from src.common.types import InterruptResumePayload, JSONObject
from src.infrastructure.database import init_db
from src.interface.adapters import adapt_langgraph_event, create_interrupt_event
from src.interface.protocol import AgentEvent
from src.interface.schemas import AgentOutputArtifact
from src.services.artifact_manager import artifact_manager
from src.services.history import history_service
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

    logger.info("✅ [Lifespan] Initialization complete.")
    yield
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
        f"📡 [Server] Starting event_generator for {thread_id} at seq {seq_counter}..."
    )

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
                f"📤 [Server] Dispatching batched tokens ({len(delta_buffer)}) from {last_delta.source}"
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
            # logger.debug(f"🔍 [Server] Raw Event: {event['event']} | Name: {event.get('name')} | Metadata: {event.get('metadata')}")
            # Check for batching/flushing BEFORE adapting the next event
            # to ensure we don't use a duplicate seq_id

            # Handle token batching logic
            if event["event"] == "on_chat_model_stream":
                agent_events = adapt_langgraph_event(
                    event, thread_id, seq_counter, run_id
                )

                # We expect only ONE event for token streaming usually, but let's be robust
                for agent_event in agent_events:
                    if agent_event.type == "content.delta":
                        # Flush if source changed or buffer reached threshold
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
                continue  # Wait for more tokens

            # If it's not a stream chunk, or it's a stream chunk from a new source:
            # First, flush any pending deltas
            await flush_deltas()

            # Now adapt the current event with the fresh seq_counter
            agent_events = adapt_langgraph_event(event, thread_id, seq_counter, run_id)

            for agent_event in agent_events:
                msg = f"data: {agent_event.model_dump_json()}\n\n"
                logger.info(
                    f"📤 [Server] Dispatching event {seq_counter}: {agent_event.type} from {agent_event.source}"
                )

                event_replay_buffers[thread_id].append(msg)
                if len(event_replay_buffers[thread_id]) > 50:
                    event_replay_buffers[thread_id].pop(0)

                for q in running_queues[thread_id][:]:
                    await q.put(msg)

                seq_counter += 1
                thread_sequences[thread_id] = seq_counter

            # Internal housekeeping: save AI messages to history
            # if event["event"] == "on_chat_model_end":
            #     output = event["data"]["output"]
            #     if isinstance(output, BaseMessage):
            #         try:
            #             await history_service.save_message(thread_id, output)
            #         except Exception as e:
            #             logger.error(f"❌ [Server] history save failed: {e}")

        # Final flush after the stream ends
        await flush_deltas()

        # 2. Check for interrupts after graph pauses
        snapshot = await graph.aget_state(config)
        if snapshot.next:
            for task in snapshot.tasks:
                if task.interrupts:
                    for i in task.interrupts:
                        # Resolve the internal node name to a high-level agent ID if possible
                        # Resolve the internal node name to a high-level agent ID
                        # using the runtime lookup map (Zero Config)
                        agent_id = agent_lookup.get(task.name)
                        source = agent_id or task.name

                        agent_event = create_interrupt_event(
                            i.value, thread_id, seq_counter, run_id, source=source
                        )
                        msg = f"data: {agent_event.model_dump_json()}\n\n"
                        logger.info(
                            f"📤 [Server] Dispatching interrupt: {agent_event.type}"
                        )

                        event_replay_buffers[thread_id].append(msg)
                        for q in running_queues[thread_id][:]:
                            await q.put(msg)
                        seq_counter += 1
                        thread_sequences[thread_id] = seq_counter
        else:
            # 3. Workflow Completed Successfully
            # If there are no next steps, the graph execution has finished.
            done_event = AgentEvent(
                thread_id=thread_id,
                run_id=run_id,
                seq_id=seq_counter,
                type="lifecycle.status",
                source="System",
                data={"status": "done"},
            )
            msg = f"data: {done_event.model_dump_json()}\n\n"
            logger.info(
                f"📤 [Server] Dispatching event {seq_counter}: lifecycle.status=done"
            )

            event_replay_buffers[thread_id].append(msg)
            if len(event_replay_buffers[thread_id]) > 50:
                event_replay_buffers[thread_id].pop(0)

            for q in running_queues[thread_id][:]:
                await q.put(msg)

            seq_counter += 1
            thread_sequences[thread_id] = seq_counter

    except Exception as e:
        logger.error(f"❌ [Server] Error in {thread_id}: {str(e)}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")

        error_event = AgentEvent(
            thread_id=thread_id,
            run_id=run_id,
            seq_id=seq_counter,
            type="error",
            source="System",
            data={"message": str(e)},
        )
        msg = f"data: {error_event.model_dump_json()}\n\n"
        for q in running_queues[thread_id][:]:
            await q.put(msg)
    finally:
        # Signal EOF to all queues
        for q in running_queues[thread_id][:]:
            await q.put(None)

        # Keep buffer for a few seconds to let pending GETs finish
        await asyncio.sleep(2)

        # Cleanup
        if thread_id in active_tasks:
            del active_tasks[thread_id]
        if thread_id in running_queues:
            del running_queues[thread_id]
        if thread_id in event_replay_buffers:
            del event_replay_buffers[thread_id]
        logger.info(f"🏁 [Server] Task for {thread_id} finished.")


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
                    id=getattr(m, "id", f"msg_{id(m)}"),
                    role=role,
                    content=str(m.content),
                    type=msg_type,
                    data=m.additional_kwargs.get("data"),
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
        from src.interface.mappers import NodeOutputMapper

        agent_outputs = NodeOutputMapper.map_all_outputs(snapshot.values)
        node_statuses = _normalize_statuses(snapshot.values.get("node_statuses"))
        last_seq_id = max(thread_sequences.get(thread_id, 1) - 1, 0)

        return ThreadStateResponse(
            thread_id=thread_id,
            messages=messages,
            interrupts=current_interrupts,
            resolved_ticker=fundamental.get("resolved_ticker"),
            status=fundamental.get("status"),
            next=snapshot.next,
            is_running=thread_id in active_tasks,
            node_statuses=node_statuses,
            agent_outputs=agent_outputs,
            last_seq_id=last_seq_id,
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
        from src.interface.mappers import NodeOutputMapper

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


@app.get("/api/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    """Retrieve artifact data with HTTP caching."""
    from fastapi.responses import JSONResponse

    artifact = await artifact_manager.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return JSONResponse(
        content=artifact.data,
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
