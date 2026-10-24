"""FastAPI composition root for the finance workflow runtime."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Literal, Protocol

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from src.analysis_runtime.application.ports import GraphRunner, OwnerPort
from src.analysis_runtime.application.runtime_service import AnalysisRuntimeService
from src.analysis_runtime.domain.contracts import Activity
from src.analysis_runtime.infrastructure import (
    BoundedNotificationHub,
    SqlAlchemyActivityRepository,
)
from src.analysis_runtime.interface.routes import router as analysis_runtime_router
from src.auth.entrypoint import (
    Principal,
    auth_router,
    get_ownership_service,
    require_current_user,
)
from src.infrastructure.database import init_db
from src.interface.artifacts.artifact_api_models import (
    ArtifactApiResponse,
    validate_artifact_api_response,
)
from src.llm_provider.entrypoint import (
    close_llm_provider,
    llm_settings_router,
    provider_keys_router,
)
from src.model_inference.entrypoint import close_model_inference
from src.observability.routes import router as observability_router
from src.search_settings import search_settings_router
from src.search_settings.composition.routes import close_search_service
from src.services.artifact_manager import artifact_manager
from src.workflow.graph import get_graph


class EventGraph(Protocol):
    def astream_events(
        self,
        input_data: Command[object] | dict[str, object],
        config: RunnableConfig | None = None,
        *,
        version: Literal["v1", "v2"] = "v2",
    ) -> AsyncIterator[Mapping[str, object]]: ...


class OwnedThreadPort(OwnerPort):
    async def owns(self, *, principal_id: str, thread_id: str) -> bool:
        return await get_ownership_service().owns(
            user_id=principal_id, resource_type="thread", resource_id=thread_id
        )

    async def claim(self, *, principal_id: str, thread_id: str) -> bool:
        return await get_ownership_service().claim(
            user_id=principal_id, resource_type="thread", resource_id=thread_id
        )


class LangGraphRunner(GraphRunner):
    """Translate LangGraph callback values into application-owned activities."""

    def __init__(self, graph: EventGraph) -> None:
        self._graph = graph

    async def run(
        self,
        *,
        thread_id: str,
        run_id: str,
        input_data: Mapping[str, object],
        principal_id: str,
    ) -> AsyncIterator[Activity]:
        message = input_data.get("message")
        resume_payload = input_data.get("resume_payload")
        if isinstance(message, str) and message:
            graph_input: Command[object] | dict[str, object] = {
                "messages": [HumanMessage(content=message)],
                "user_query": message,
            }
        elif isinstance(resume_payload, Mapping):
            graph_input = Command(resume=dict(resume_payload))
        else:
            graph_input = {}
        async for raw in self._graph.astream_events(
            graph_input,
            config={"configurable": {"thread_id": thread_id}},
            version="v2",
        ):
            event_name = str(raw.get("event", ""))
            if not event_name.startswith("on_"):
                continue
            metadata = raw.get("metadata")
            metadata_map = metadata if isinstance(metadata, Mapping) else {}
            activity_id = str(
                metadata_map.get("agent_id") or raw.get("name") or "workflow"
            )
            status = (
                "running"
                if event_name.endswith("_start")
                else "failed"
                if event_name.endswith("_error")
                else "completed"
            )
            yield Activity(
                activity_id=activity_id,
                thread_id=thread_id,
                run_id=run_id,
                scope_path=tuple(part for part in activity_id.split(".") if part),
                kind="tool" if "tool" in event_name else "node",
                status=status,
                label=str(raw.get("name") or "Workflow activity")[:160],
                progress=100 if status == "completed" else None,
                attempt=1,
            )


def _cors_origins() -> list[str]:
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "")
    return [
        item.strip().rstrip("/") for item in configured.split(",") if item.strip()
    ] or [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    graph = await get_graph()
    app.state.analysis_runtime = AnalysisRuntimeService(
        repository=SqlAlchemyActivityRepository(),
        owner=OwnedThreadPort(),
        runner=LangGraphRunner(graph),
        hub=BoundedNotificationHub(),
    )
    try:
        yield
    finally:
        await close_search_service()
        await close_llm_provider()
        await close_model_inference()


app = FastAPI(
    title="Neuro-Symbolic Valuation Engine API",
    version="3.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
)
app.include_router(auth_router)
app.include_router(provider_keys_router)
app.include_router(llm_settings_router)
app.include_router(search_settings_router)
app.include_router(analysis_runtime_router)
app.include_router(observability_router)


@app.get("/health", tags=["Operations"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["Operations"])
async def ready(request: Request) -> dict[str, str]:
    if not hasattr(request.app.state, "analysis_runtime"):
        raise HTTPException(status_code=503, detail="application is still starting")
    return {"status": "ready"}


artifact_router = APIRouter(prefix="/api/v1/artifacts", tags=["Artifacts"])


@artifact_router.get("/{artifact_id}", response_model=ArtifactApiResponse)
async def get_artifact(
    artifact_id: str,
    principal: Principal = Depends(require_current_user),
) -> JSONResponse:
    artifact = await artifact_manager.get_artifact(artifact_id)
    if artifact is None or artifact.thread_id is None:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    owned = await get_ownership_service().owns(
        user_id=principal.user_id,
        resource_type="thread",
        resource_id=artifact.thread_id,
    )
    if not owned:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    envelope = await artifact_manager.get_artifact_envelope(artifact_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    validated = validate_artifact_api_response(
        envelope.model_dump(mode="json"), context=f"artifact {artifact_id}"
    )
    return JSONResponse(
        content=validated.model_dump(mode="json"),
        headers={
            "Cache-Control": "private, max-age=3600",
            "ETag": f'"{artifact_id}"',
        },
    )


app.include_router(artifact_router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
