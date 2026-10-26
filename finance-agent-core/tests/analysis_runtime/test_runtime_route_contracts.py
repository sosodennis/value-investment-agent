from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from src.analysis_runtime.application.runtime_service import AnalysisRuntimeService
from src.analysis_runtime.domain.contracts import Activity
from src.analysis_runtime.infrastructure.memory_repository import (
    InMemoryActivityRepository,
)
from src.analysis_runtime.interface.routes import router
from src.auth.interface.contracts import Principal
from src.auth.interface.dependencies import require_current_user


class Owner:
    async def owns(self, *, principal_id: str, thread_id: str) -> bool:
        return principal_id == "user-1" and thread_id == "thread-1"

    async def claim(self, *, principal_id: str, thread_id: str) -> bool:
        return await self.owns(principal_id=principal_id, thread_id=thread_id)


class Runner:
    async def run(self, **kwargs):
        yield Activity(
            activity_id="analysis",
            thread_id=kwargs["thread_id"],
            run_id=kwargs["run_id"],
            scope_path=("fundamental_analysis",),
            kind="phase",
            status="completed",
            label="Fundamental analysis",
            attempt=1,
        )


@pytest.mark.asyncio
async def test_activities_route_loads_an_exact_historical_run_after_rerun() -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_current_user] = lambda: Principal(
        user_id="user-1", subject="user-1", email="user@example.test"
    )
    service = AnalysisRuntimeService(
        repository=InMemoryActivityRepository(), owner=Owner(), runner=Runner()
    )
    app.state.analysis_runtime = service

    first_run = await service.start(
        principal_id="user-1",
        thread_id="thread-1",
        input_data={"message": "AAPL"},
    )
    await service._tasks["thread-1"]
    second_run = await service.start(
        principal_id="user-1",
        thread_id="thread-1",
        input_data={"message": "MSFT"},
    )
    await service._tasks["thread-1"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        old_snapshot = await client.get(
            f"/api/v1/threads/thread-1/activities?run_id={first_run}"
        )
        latest_snapshot = await client.get("/api/v1/threads/thread-1/activities")

    assert old_snapshot.status_code == 200
    assert old_snapshot.json()["run_id"] == first_run
    assert old_snapshot.json()["run_status"] == "completed"
    assert latest_snapshot.status_code == 200
    assert latest_snapshot.json()["run_id"] == second_run
