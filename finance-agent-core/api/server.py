"""FastAPI composition root for the finance workflow runtime."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from src.analysis_runtime.application.ports import OwnerPort
from src.analysis_runtime.application.runtime_service import AnalysisRuntimeService
from src.analysis_runtime.infrastructure import (
    BoundedNotificationHub,
    LangGraphRunner,
    SqlAlchemyActivityRepository,
)
from src.analysis_runtime.interface.routes import router as analysis_runtime_router
from src.audit.entrypoint import audit_router
from src.audit.interface.middleware import CorrelationIdMiddleware
from src.auth.entrypoint import (
    auth_router,
    get_ownership_service,
    invitation_router,
    organization_router,
)
from src.dashboard.infrastructure import (
    HttpReadinessProvider,
    MarketMoversService,
    YahooMarketMoversProvider,
)
from src.dashboard.routes import router as dashboard_router
from src.infrastructure.migrations import assert_migrations_complete
from src.interface.artifacts.routes import router as artifact_router
from src.interface.origins import frontend_origins
from src.llm_provider.entrypoint import (
    close_llm_provider,
    llm_settings_router,
    provider_keys_router,
)
from src.model_inference.entrypoint import close_model_inference
from src.notifications.entrypoint import get_notification_worker, notifications_router
from src.observability.routes import router as observability_router
from src.search_settings import search_settings_router
from src.search_settings.composition.routes import close_search_service
from src.shared.kernel.rate_limit import close_rate_limiter
from src.workflow.graph import get_graph


class OwnedThreadPort(OwnerPort):
    async def owns(self, *, principal_id: str, thread_id: str) -> bool:
        return await get_ownership_service().owns(
            user_id=principal_id, resource_type="thread", resource_id=thread_id
        )

    async def claim(self, *, principal_id: str, thread_id: str) -> bool:
        return await get_ownership_service().claim(
            user_id=principal_id, resource_type="thread", resource_id=thread_id
        )


def _cors_origins() -> list[str]:
    return list(frontend_origins())


@asynccontextmanager
async def lifespan(app: FastAPI):
    await assert_migrations_complete()
    graph = await get_graph()
    runtime = AnalysisRuntimeService(
        repository=SqlAlchemyActivityRepository(),
        owner=OwnedThreadPort(),
        runner=LangGraphRunner(graph),
        hub=BoundedNotificationHub(),
    )
    app.state.analysis_runtime = runtime
    await runtime.recover_pending_resumes()
    await runtime.recover_pending_retries()
    app.state.market_movers_service = MarketMoversService(YahooMarketMoversProvider())
    app.state.readiness_provider = HttpReadinessProvider()
    notification_stop = asyncio.Event()
    notification_worker_task = asyncio.create_task(
        get_notification_worker().serve(stop_event=notification_stop)
    )
    app.state.notification_worker_task = notification_worker_task
    try:
        yield
    finally:
        notification_stop.set()
        await notification_worker_task
        await close_search_service()
        await close_llm_provider()
        await close_model_inference()
        await close_rate_limiter()


app = FastAPI(
    title="Neuro-Symbolic Valuation Engine API",
    version="3.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    _request: Request, error: RequestValidationError
) -> JSONResponse:
    details = [
        {
            "type": str(issue.get("type", "validation_error")),
            "loc": [str(part) for part in issue.get("loc", ())],
            "msg": "Invalid request value.",
        }
        for issue in error.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": details})


app.add_middleware(
    CorrelationIdMiddleware,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "Idempotency-Key"],
    expose_headers=["X-Request-ID"],
)
app.include_router(auth_router)
app.include_router(organization_router)
app.include_router(invitation_router)
app.include_router(provider_keys_router)
app.include_router(llm_settings_router)
app.include_router(search_settings_router)
app.include_router(analysis_runtime_router)
app.include_router(dashboard_router)
app.include_router(observability_router)
app.include_router(artifact_router)
app.include_router(notifications_router)
app.include_router(audit_router)


def _openapi() -> dict[str, object]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
        description=app.description,
    )
    event_response = (
        schema.get("paths", {})
        .get("/api/v1/threads/{thread_id}/events", {})
        .get("get", {})
        .get("responses", {})
        .get("200", {})
    )
    content = event_response.get("content", {})
    # FastAPI uses the declared union model to register its component schemas.
    # The wire response remains SSE text; the union describes each data frame.
    content.pop("application/json", None)
    stream_schema = content.get("text/event-stream", {}).get("schema", {})
    stream_schema.pop("oneOf", None)
    stream_schema.pop("discriminator", None)
    stream_schema.pop("title", None)
    stream_schema["type"] = "string"
    app.openapi_schema = schema
    return schema


app.openapi = _openapi


@app.get("/health", tags=["Operations"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["Operations"])
async def ready(request: Request) -> dict[str, str]:
    if not hasattr(request.app.state, "analysis_runtime"):
        raise HTTPException(status_code=503, detail="application is still starting")
    return {"status": "ready"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
