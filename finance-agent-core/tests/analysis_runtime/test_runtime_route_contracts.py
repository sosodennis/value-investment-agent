from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from src.analysis_runtime.application.runtime_service import AnalysisRuntimeService
from src.analysis_runtime.domain.contracts import (
    Activity,
    InteractionIdentity,
    InteractionRequested,
    TickerCandidate,
    TickerSelectionRequest,
)
from src.analysis_runtime.infrastructure.memory_repository import (
    InMemoryActivityRepository,
)
from src.analysis_runtime.interface.routes import ResumeRequest, RunRequest, router
from src.auth.entrypoint import require_current_user_mutation
from src.auth.interface.contracts import Principal
from src.auth.interface.dependencies import require_current_user


def test_start_request_rejects_unbound_resume_payload() -> None:
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {"message": "Apple", "resume_payload": {"selected_symbol": "AAPL"}}
        )


def test_resume_request_requires_full_interaction_identity() -> None:
    with pytest.raises(ValidationError):
        ResumeRequest.model_validate(
            {
                "response": {
                    "type": "ticker_selection",
                    "selected_symbol": "AAPL",
                }
            }
        )

    request = ResumeRequest.model_validate(
        {
            "identity": {
                "thread_id": "thread-1",
                "run_id": "run-1",
                "activity_id": "intent.clarifying",
                "interaction_id": "interaction-1",
            },
            "response": {
                "type": "ticker_selection",
                "selected_symbol": "AAPL",
            },
        }
    )
    assert request.identity == InteractionIdentity(
        thread_id="thread-1",
        run_id="run-1",
        activity_id="intent.clarifying",
        interaction_id="interaction-1",
    )


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


class InterruptingRunner:
    async def run(self, **kwargs):
        activity = Activity(
            activity_id="intent.clarifying",
            thread_id=kwargs["thread_id"],
            run_id=kwargs["run_id"],
            scope_path=("intent", "clarifying"),
            kind="node",
            status="waiting"
            if "interrupt_response" not in kwargs["input_data"]
            else "completed",
            label="Ticker resolution",
            attempt=1,
        )
        if activity.status == "waiting":
            yield InteractionRequested(
                activity=activity,
                identity=InteractionIdentity(
                    thread_id=kwargs["thread_id"],
                    run_id=kwargs["run_id"],
                    activity_id=activity.activity_id,
                    interaction_id="interaction-1",
                ),
                request=TickerSelectionRequest(
                    type="ticker_selection",
                    title="Choose the company",
                    description="Select the intended ticker.",
                    candidates=[
                        TickerCandidate(
                            symbol="AAPL", name="Apple Inc.", confidence=0.99
                        )
                    ],
                ),
            )
        else:
            yield activity.model_copy(
                update={"activity_id": "workflow", "scope_path": ("workflow",)}
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


@pytest.mark.asyncio
async def test_http_interaction_snapshot_resume_and_completion_contract() -> None:
    app = FastAPI()
    app.include_router(router)

    def principal() -> Principal:
        return Principal(user_id="user-1", subject="user-1", email="user@example.test")

    app.dependency_overrides[require_current_user] = principal
    app.dependency_overrides[require_current_user_mutation] = principal
    service = AnalysisRuntimeService(
        repository=InMemoryActivityRepository(),
        owner=Owner(),
        runner=InterruptingRunner(),
    )
    app.state.analysis_runtime = service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        started = await client.post(
            "/api/v1/threads/thread-1/runs", json={"message": "Apple"}
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        await service._tasks["thread-1"]

        waiting = await client.get(
            f"/api/v1/threads/thread-1/activities?run_id={run_id}"
        )
        assert waiting.status_code == 200
        waiting_snapshot = waiting.json()
        assert waiting_snapshot["run_status"] == "waiting"
        assert waiting_snapshot["active_activities"][0]["status"] == "waiting"
        assert "interruption" not in waiting_snapshot["active_activities"][0]
        interaction = waiting_snapshot["pending_interactions"][0]
        assert interaction["identity"] == {
            "thread_id": "thread-1",
            "run_id": run_id,
            "activity_id": "intent.clarifying",
            "interaction_id": "interaction-1",
        }

        resumed = await client.post(
            f"/api/v1/threads/thread-1/runs/{run_id}/resume",
            json={
                "identity": interaction["identity"],
                "response": {"type": "ticker_selection", "selected_symbol": "AAPL"},
            },
        )
        assert resumed.status_code == 202
        assert resumed.json()["run_id"] == run_id
        await service._tasks["thread-1"]

        completed = await client.get(
            f"/api/v1/threads/thread-1/activities?run_id={run_id}"
        )

    assert completed.status_code == 200
    assert completed.json()["run_status"] == "completed"
    openapi = app.openapi()
    snapshot_schema = openapi["components"]["schemas"]["WorkflowSnapshot"]
    assert "pending_interactions" in snapshot_schema["properties"]
    assert "completed_outputs" in snapshot_schema["properties"]
    assert "WorkflowInteractionEvent" in openapi["components"]["schemas"]
    assert "WorkflowAgentOutputEvent" in openapi["components"]["schemas"]
