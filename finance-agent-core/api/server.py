"""FastAPI composition root for the finance workflow runtime."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from src.analysis_runtime.application.ports import OwnerPort
from src.analysis_runtime.application.runtime_service import AnalysisRuntimeService
from src.analysis_runtime.infrastructure import (
    BoundedNotificationHub,
    LangGraphRunner,
    SqlAlchemyActivityRepository,
)
from src.analysis_runtime.interface.routes import router as analysis_runtime_router
from src.auth.entrypoint import auth_router, get_ownership_service
from src.dashboard.infrastructure import (
    HttpReadinessProvider,
    MarketMoversService,
    YahooMarketMoversProvider,
)
from src.dashboard.routes import router as dashboard_router
from src.infrastructure.migrations import assert_migrations_complete
from src.interface.artifacts.routes import router as artifact_router
from src.llm_provider.entrypoint import (
    close_llm_provider,
    llm_settings_router,
    provider_keys_router,
)
from src.model_inference.entrypoint import close_model_inference
from src.observability.routes import router as observability_router
from src.search_settings import search_settings_router
from src.search_settings.composition.routes import close_search_service
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
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "")
    return [
        item.strip().rstrip("/") for item in configured.split(",") if item.strip()
    ] or [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await assert_migrations_complete()
    graph = await get_graph()
    app.state.analysis_runtime = AnalysisRuntimeService(
        repository=SqlAlchemyActivityRepository(),
        owner=OwnedThreadPort(),
        runner=LangGraphRunner(graph),
        hub=BoundedNotificationHub(),
    )
    app.state.market_movers_service = MarketMoversService(YahooMarketMoversProvider())
    app.state.readiness_provider = HttpReadinessProvider()
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
app.include_router(dashboard_router)
app.include_router(observability_router)
app.include_router(artifact_router)


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
