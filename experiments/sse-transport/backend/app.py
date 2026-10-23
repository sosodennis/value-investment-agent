from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from importlib.metadata import version
from typing import NotRequired, TypedDict

from fastapi import Cookie, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

try:
    from fastapi.sse import EventSourceResponse, ServerSentEvent
except ImportError:  # FastAPI < 0.135.0
    EventSourceResponse = None
    ServerSentEvent = None


class ProbeState(TypedDict):
    count: int
    interval_ms: int
    after_seq: int
    complete: NotRequired[bool]


async def emit_probe_events(state: ProbeState) -> dict[str, bool]:
    writer = get_stream_writer()
    for seq in range(state["after_seq"] + 1, state["count"] + 1):
        writer({"seq": seq, "emitted_at": time.time(), "value": f"token-{seq}"})
        await asyncio.sleep(state["interval_ms"] / 1000)
    return {"complete": True}


_builder = StateGraph(ProbeState)
_builder.add_node("emit", emit_probe_events)
_builder.set_entry_point("emit")
_builder.set_finish_point("emit")
_graph = _builder.compile()

app = FastAPI(title="SSE transport compatibility probe")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        os.environ.get("PROBE_FRONTEND_ORIGIN", "http://127.0.0.1:13100"),
        "http://localhost:13100",
    ],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


async def graph_events(
    *, count: int, interval_ms: int, after_seq: int
) -> AsyncIterator[dict[str, object]]:
    async for chunk in _graph.astream(
        {"count": count, "interval_ms": interval_ms, "after_seq": after_seq},
        stream_mode="custom",
        version="v2",
    ):
        if isinstance(chunk, dict) and chunk.get("type") == "custom":
            yield chunk["data"]
        elif isinstance(chunk, dict) and "seq" in chunk:
            yield chunk


def sse_frame(event: dict[str, object]) -> str:
    seq = int(event["seq"])
    payload = json.dumps(event, separators=(",", ":"))
    return f"id: {seq}\nevent: probe\ndata: {payload}\n\n"


MANUAL_STREAM_HEADERS = os.environ.get("PROBE_MANUAL_STREAM_HEADERS", "1") != "0"
STREAM_HEADERS = (
    {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
    }
    if MANUAL_STREAM_HEADERS
    else {}
)
STREAM_NO_TRANSFORM = os.environ.get("PROBE_STREAM_NO_TRANSFORM") == "1"


@app.middleware("http")
async def set_stream_no_transform(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    response = await call_next(request)
    if STREAM_NO_TRANSFORM and request.url.path.startswith("/stream/"):
        cache_control = response.headers.get("Cache-Control")
        if cache_control and "no-transform" not in cache_control:
            response.headers["Cache-Control"] = f"{cache_control}, no-transform"
        elif not cache_control:
            response.headers["Cache-Control"] = "no-cache, no-transform"
    return response


async def manual_body(
    *, count: int, interval_ms: int, after_seq: int
) -> AsyncIterator[str]:
    async for event in graph_events(
        count=count, interval_ms=interval_ms, after_seq=after_seq
    ):
        yield sse_frame(event)
    yield 'event: terminal\ndata: {"status":"done"}\n\n'


@app.get("/stream/manual")
async def manual_stream(
    count: int = Query(default=6, ge=1, le=30),
    interval_ms: int = Query(default=250, ge=10, le=5000),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    after_seq = max(0, int(last_event_id or "0"))
    return StreamingResponse(
        manual_body(count=count, interval_ms=interval_ms, after_seq=after_seq),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


@app.get("/stream/authenticated")
async def authenticated_stream(
    probe_session: str | None = Cookie(default=None),
    count: int = Query(default=6, ge=1, le=30),
    interval_ms: int = Query(default=250, ge=10, le=5000),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    if probe_session != "authenticated":
        raise HTTPException(status_code=401, detail="probe session required")
    after_seq = max(0, int(last_event_id or "0"))
    return StreamingResponse(
        manual_body(count=count, interval_ms=interval_ms, after_seq=after_seq),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


if EventSourceResponse is not None and ServerSentEvent is not None:

    @app.get("/stream/native", response_class=EventSourceResponse)
    async def native_stream(
        count: int = Query(default=6, ge=1, le=30),
        interval_ms: int = Query(default=250, ge=10, le=5000),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> AsyncIterator[ServerSentEvent]:
        after_seq = max(0, int(last_event_id or "0"))
        yield ServerSentEvent(comment="connected")
        async for event in graph_events(
            count=count, interval_ms=interval_ms, after_seq=after_seq
        ):
            yield ServerSentEvent(
                id=str(event["seq"]),
                event="probe",
                data=event,
            )
        yield ServerSentEvent(event="terminal", data={"status": "done"})


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "fastapi_version": version("fastapi"),
        "langgraph_version": version("langgraph"),
        "langchain_core_version": version("langchain-core"),
        "starlette_version": version("starlette"),
        "native_sse": EventSourceResponse is not None,
        "stream_no_transform": STREAM_NO_TRANSFORM,
        "manual_stream_headers": MANUAL_STREAM_HEADERS,
    }
