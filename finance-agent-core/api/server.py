import asyncio
import json
import os
import sys
from collections import defaultdict
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.types import Command

from src.infrastructure.database import init_db
from src.services.history import history_service
from src.workflow.graph import get_graph
from src.workflow.interrupts import InterruptValue
from src.workflow.state import AgentState

app = FastAPI(
    title="Neuro-Symbolic Valuation Engine API",
    version="2.0",
    description="Pure FastAPI implementation for FinGraph Valuation Agent (Path B)",
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
    resume_payload: Any | None = None


class JobManager:
    """
    Manages background graph execution tasks and broadcasts events to listeners.
    Ensures only one job per thread_id runs at a time.
    """

    def __init__(self):
        self.jobs: dict[str, asyncio.Task] = {}
        self.queues: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def is_running(self, thread_id: str) -> bool:
        task = self.jobs.get(thread_id)
        return task is not None and not task.done()

    async def _run_graph(self, thread_id: str, input_data: Any, config: dict):
        try:
            print(f"🚀 [JobManager] Starting job for {thread_id}")
            graph = await get_graph()

            # Use centralized agent configuration for hidden nodes
            # Can be overridden with DEBUG_SHOW_ALL_STREAMING=true environment variable
            from src.config.agents import get_hidden_nodes

            DEBUG_MODE = (
                os.environ.get("DEBUG_SHOW_ALL_STREAMING", "false").lower() == "true"
            )
            HIDDEN_NODES = set() if DEBUG_MODE else get_hidden_nodes()

            if DEBUG_MODE:
                print("🔍 [JobManager] DEBUG MODE: Showing all token streaming")

            # 1. Stream events
            async for event in graph.astream_events(
                input_data, config=config, version="v2"
            ):
                # Filtering logic: Only block internal LLM generation (tokens) for specific nodes.
                # Allow on_chain_end and other events so status updates and interrupts flow through.
                node_name = event.get("metadata", {}).get("langgraph_node", "")
                event_type = event["event"]

                if event_type == "on_chat_model_stream" and node_name in HIDDEN_NODES:
                    continue

                try:
                    # Broadcast
                    await self._broadcast(thread_id, {"type": "event", "data": event})

                    # Persist AI messages when they finish
                    if event_type == "on_chat_model_end":
                        # Only persist if it's not a hidden node or if we want to include tool calls in history
                        # For now, let's persist the assistant response
                        if node_name not in HIDDEN_NODES:
                            output = event["data"]["output"]
                            # Only persist if it's a valid LangChain message
                            if isinstance(output, BaseMessage):
                                try:
                                    await history_service.save_message(
                                        thread_id, output
                                    )
                                except Exception as e:
                                    print(
                                        f"❌ [JobManager] save_message failed for {node_name}: {e}"
                                    )
                                    # Don't re-raise here to avoid crashing the whole job for a history save failure
                                    pass
                            else:
                                print(
                                    f"ℹ️ [JobManager] Skipping persistence for non-message output from {node_name}: {type(output)}"
                                )
                                # Double check if it strangely had .content
                                if hasattr(output, "content"):
                                    print(
                                        f"⚠️ [JobManager] WEIRD: Object {type(output)} has .content but is not BaseMessage!"
                                    )

                    # Persist messages manually added via Command updates (e.g. financial_health, clarification)
                    elif event_type == "on_chain_end":
                        output = event["data"].get("output")
                        if isinstance(output, Command) and output.update:
                            messages = output.update.get("messages")
                            if messages:
                                if not isinstance(messages, list):
                                    messages = [messages]
                                try:
                                    await history_service.save_messages(
                                        thread_id, messages
                                    )
                                except Exception as e:
                                    print(
                                        f"❌ [JobManager] save_messages failed for {node_name}: {e}"
                                    )
                                    # Don't re-raise here to avoid crashing the whole job for a history save failure
                                    pass
                except Exception as e:
                    print(
                        f"❌ [JobManager] Error processing event {event_type} from {node_name}: {e}"
                    )
                    raise e

            # 2. Check for interrupts
            snapshot = await graph.aget_state(config)
            if snapshot.next:
                current_interrupts = []
                for task in snapshot.tasks:
                    if task.interrupts:
                        for i in task.interrupts:
                            try:
                                val = InterruptValue.model_validate(i.value)
                                current_interrupts.append(val.model_dump())
                            except Exception:
                                current_interrupts.append(i.value)

                if current_interrupts:
                    await self._broadcast(
                        thread_id, {"type": "interrupt", "data": current_interrupts}
                    )

        except Exception as e:
            print(f"❌ [JobManager] Error in {thread_id}: {str(e)}", flush=True)
            await self._broadcast(thread_id, {"type": "error", "data": str(e)})
        finally:
            print(f"🏁 [JobManager] Job for {thread_id} finished.")
            await self._broadcast(thread_id, None)  # Signal EOF
            if thread_id in self.jobs:
                del self.jobs[thread_id]

    async def _broadcast(self, thread_id: str, payload: Any):
        if thread_id not in self.queues:
            return

        # Standardize event serialization
        def json_serializable(obj):
            try:
                # Handle Enums first (before model_dump check since many Pydantic models include enums)
                from enum import Enum

                if isinstance(obj, Enum):
                    return obj.value
                if isinstance(obj, Command):
                    return {"update": obj.update, "goto": obj.goto, "graph": obj.graph}
                # Handle Pydantic models
                if hasattr(obj, "model_dump"):
                    return obj.model_dump(mode="json")
                if hasattr(obj, "dict"):
                    return obj.dict()
                # Handle datetime
                from datetime import datetime

                if isinstance(obj, datetime):
                    return obj.isoformat()
                return str(obj)
            except Exception as e:
                print(f"json_serializable fallback for {type(obj)}: {e}")
                return str(obj)

        try:
            msg = (
                f"data: {json.dumps(payload, default=json_serializable)}\n\n"
                if payload
                else None
            )
        except TypeError:
            print(f"❌ [JobManager] Serialization failed for payload: {payload}")
            # Try to identify which part failed
            try:
                if isinstance(payload, dict) and "data" in payload:
                    data = payload["data"]
                    if isinstance(data, dict):
                        for k, v in data.items():
                            print(f"Key: {k}, Type: {type(v)}")
                            try:
                                json.dumps(v, default=json_serializable)
                            except TypeError:
                                print(f"FAILED on key '{k}' with value: {v}")
            except Exception:
                pass
            # Don't re-raise serialization errors to avoid crashing the job
            print(
                "⚠️ [JobManager] Serialization failed, skipping broadcast for this event."
            )
            return

        # Send to all connected queues
        for q in self.queues[thread_id][:]:
            try:
                await q.put(msg)
            except Exception:
                self.queues[thread_id].remove(q)

    def start_job(self, thread_id: str, input_data: Any, config: dict):
        if self.is_running(thread_id):
            return False
        self.jobs[thread_id] = asyncio.create_task(
            self._run_graph(thread_id, input_data, config)
        )
        return True

    def get_stream(self, thread_id: str):
        q = asyncio.Queue()
        self.queues[thread_id].append(q)
        return q

    def unsubscribe(self, thread_id: str, q: asyncio.Queue):
        if thread_id in self.queues and q in self.queues[thread_id]:
            self.queues[thread_id].remove(q)
            if not self.queues[thread_id]:
                del self.queues[thread_id]


job_manager = JobManager()


@app.get("/history/{thread_id}")
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


@app.get("/thread/{thread_id}")
async def get_thread_history(thread_id: str):
    """Retrieve history and job status."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
        graph = await get_graph()
        snapshot = await graph.aget_state(config)

        messages = []
        for m in snapshot.values.get("messages", []):
            role = "assistant" if isinstance(m, AIMessage) else "user"
            messages.append(
                {
                    "id": getattr(m, "id", f"msg_{id(m)}"),
                    "role": role,
                    "content": m.content,
                    "type": m.additional_kwargs.get("type", "text"),
                    "data": m.additional_kwargs.get("data"),
                }
            )

        current_interrupts = []
        for task in snapshot.tasks:
            if task.interrupts:
                for i in task.interrupts:
                    try:
                        val = InterruptValue.model_validate(i.value)
                        current_interrupts.append(val.model_dump())
                    except Exception:
                        current_interrupts.append(i.value)

        # Helper to safely extract nested context
        def get_context(name: str) -> dict:
            val = snapshot.values.get(name)
            if val and hasattr(val, "model_dump"):
                return val.model_dump()
            return val or {}

        fundamental = get_context("fundamental")
        debate = get_context("debate")

        agent_outputs = {
            "planner": {
                "financial_reports": fundamental.get("financial_reports", []),
                "resolved_ticker": fundamental.get("resolved_ticker"),
                "company_profile": fundamental.get("company_profile"),
                "approved": fundamental.get("approved"),
            },
            "executor": snapshot.values.get("extraction_output"),
            "auditor": snapshot.values.get("audit_output"),
            "calculator": snapshot.values.get("calculation_output"),
            "debate": debate.get("conclusion"),
        }

        res = {
            "thread_id": thread_id,
            "messages": messages,
            "interrupts": current_interrupts,
            "resolved_ticker": fundamental.get("resolved_ticker"),
            "status": fundamental.get("status"),
            "next": snapshot.next,
            "is_running": job_manager.is_running(thread_id),
            "node_statuses": snapshot.values.get("node_statuses", {}),
            "financial_reports": fundamental.get("financial_reports", []),
            "agent_outputs": agent_outputs,
        }
        print(
            f"DEBUG: get_thread_history({thread_id}) -> is_running={res['is_running']}"
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/thread/{thread_id}/agents")
async def get_agent_statuses(thread_id: str):
    """Retrieve node statuses and financial reports for the dashboard."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
        graph = await get_graph()
        snapshot = await graph.aget_state(config)

        # Helper to safely extract nested context
        def get_context(name: str) -> dict:
            val = snapshot.values.get(name)
            if val and hasattr(val, "model_dump"):
                return val.model_dump()
            return val or {}

        fundamental = get_context("fundamental")
        debate = get_context("debate")

        agent_outputs = {
            "planner": {
                "financial_reports": fundamental.get("financial_reports", []),
                "resolved_ticker": fundamental.get("resolved_ticker"),
                "company_profile": fundamental.get("company_profile"),
                "approved": fundamental.get("approved"),
            },
            "executor": snapshot.values.get("extraction_output"),
            "auditor": snapshot.values.get("audit_output"),
            "calculator": snapshot.values.get("calculation_output"),
            "debate": debate.get("conclusion"),
        }
        return {
            "node_statuses": snapshot.values.get("node_statuses", {}),
            "financial_reports": fundamental.get("financial_reports", []),
            "current_node": snapshot.values.get("current_node"),
            "agent_outputs": agent_outputs,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/stream/{thread_id}")
async def attach_stream(thread_id: str):
    """Attach to an existing or recently started background job."""

    async def event_generator():
        # Quick check if job is already done before we subscribe
        if not job_manager.is_running(thread_id):
            print(
                f"⚠️ [attach_stream] Request for finished job {thread_id}. Closing immediately."
            )
            return

        q = job_manager.get_stream(thread_id)
        try:
            while True:
                msg = await q.get()
                if msg is None:
                    break  # EOF
                yield msg
        finally:
            job_manager.unsubscribe(thread_id, q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/stream")
async def stream_agent(body: RequestSchema):
    """Start or resume a job."""
    print(f"DEBUG: stream_agent called with body: {body}")
    thread_id = body.thread_id
    config = {"configurable": {"thread_id": thread_id}}

    if job_manager.is_running(thread_id):
        if body.message or body.resume_payload:
            raise HTTPException(
                status_code=409, detail="Job already running for this thread."
            )
        # If it's a "wakeup" call but job is already running, just return 200 to indicate OK
        return {"status": "running", "thread_id": thread_id}

    # Persist user message immediately
    if body.message:
        user_msg = HumanMessage(content=body.message)
        await history_service.save_message(thread_id, user_msg)
        input_data = AgentState(
            messages=[user_msg], user_query=body.message
        ).model_dump()
    elif body.resume_payload:
        print(f"DEBUG: Resuming with payload: {body.resume_payload}")
        input_data = Command(resume=body.resume_payload)
    else:
        input_data = None

    print(
        f"DEBUG: Starting job with input_data type: {type(input_data)} value: {input_data}"
    )
    # Start job
    job_manager.start_job(thread_id, input_data, config)
    return {"status": "started", "thread_id": thread_id}


@app.on_event("startup")
async def startup_event():
    await init_db()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
