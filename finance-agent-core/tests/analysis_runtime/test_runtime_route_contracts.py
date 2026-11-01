from __future__ import annotations

import json
from types import SimpleNamespace

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
from src.analysis_runtime.interface.routes import (
    ResumeRequest,
    RunRequest,
    WorkflowEventStreamResponse,
    activity_events,
    router,
)
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


def test_event_stream_response_disables_transforming_and_buffering() -> None:
    async def stream():
        yield ": heartbeat\n\n"

    response = WorkflowEventStreamResponse(stream())

    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"


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


class RetryableRunner:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            error = RuntimeError("provider rate limited")
            error.code = "rate_limited"
            error.retryable = True
            raise error
        yield Activity(
            activity_id="debate.verdict",
            thread_id=kwargs["thread_id"],
            run_id=kwargs["run_id"],
            scope_path=("debate", "verdict"),
            kind="node",
            status="completed",
            label="Debate verdict",
            attempt=kwargs["input_data"]["retry"]["attempt"],
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
        user_id="user-1",
        subject="user-1",
        email="user@example.test",
        organization_id="organization-1",
        membership_id="membership-1",
    )
    service = AnalysisRuntimeService(
        repository=InMemoryActivityRepository(), owner=Owner(), runner=Runner()
    )
    app.state.analysis_runtime = service

    first_run = await service.start(
        principal_id="user-1",
        thread_id="thread-1",
        input_data={"message": "AAPL"},
        organization_id="organization-1",
        membership_id="membership-1",
    )
    await service._tasks["thread-1"]
    second_run = await service.start(
        principal_id="user-1",
        thread_id="thread-1",
        input_data={"message": "MSFT"},
        organization_id="organization-1",
        membership_id="membership-1",
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
async def test_runtime_rejects_a_forged_organization_header() -> None:
    app = FastAPI()
    app.include_router(router)
    principal = Principal(
        user_id="user-1",
        subject="user-1",
        email="user@example.test",
        organization_id="organization-1",
        membership_id="membership-1",
    )
    app.dependency_overrides[require_current_user_mutation] = lambda: principal
    service = AnalysisRuntimeService(
        repository=InMemoryActivityRepository(), owner=Owner(), runner=Runner()
    )
    app.state.analysis_runtime = service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/threads/thread-1/runs",
            headers={"X-Organization-ID": "organization-attacker"},
            json={"message": "AAPL"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "organization_context_mismatch"


@pytest.mark.asyncio
async def test_event_route_streams_replayed_workflow_events_without_transform_headers() -> (
    None
):
    app = FastAPI()
    service = AnalysisRuntimeService(
        repository=InMemoryActivityRepository(), owner=Owner(), runner=Runner()
    )
    app.state.analysis_runtime = service
    run_id = await service.start(
        principal_id="user-1",
        thread_id="thread-1",
        input_data={"message": "AAPL"},
        organization_id="organization-1",
        membership_id="membership-1",
    )
    await service._tasks["thread-1"]

    response = await activity_events(
        thread_id="thread-1",
        request=SimpleNamespace(app=app),
        principal=Principal(
            user_id="user-1",
            subject="user-1",
            email="user@example.test",
            organization_id="organization-1",
            membership_id="membership-1",
        ),
        after_seq=0,
        run_id=run_id,
    )

    try:
        frame = await anext(response.body_iterator)
    finally:
        await response.body_iterator.aclose()

    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert "content-encoding" not in response.headers
    assert frame.startswith("id: 1\nevent: workflow.activity\ndata: ")
    payload = json.loads(frame.split("data: ", maxsplit=1)[1])
    assert payload["thread_id"] == "thread-1"
    assert payload["run_id"] == run_id
    assert payload["event_name"] == "workflow.activity"


@pytest.mark.asyncio
async def test_http_interaction_snapshot_resume_and_completion_contract() -> None:
    app = FastAPI()
    app.include_router(router)

    def principal() -> Principal:
        return Principal(
            user_id="user-1",
            subject="user-1",
            email="user@example.test",
            organization_id="organization-1",
            membership_id="membership-1",
        )

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
        task = service._tasks.get("thread-1")
        if task is not None:
            await task

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
        task = service._tasks.get("thread-1")
        if task is not None:
            await task

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


@pytest.mark.asyncio
async def test_authenticated_retry_endpoint_requires_key_and_returns_same_attempt() -> (
    None
):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_current_user] = lambda: Principal(
        user_id="user-1",
        subject="user-1",
        email="user@example.test",
        organization_id="organization-1",
        membership_id="membership-1",
    )
    app.dependency_overrides[require_current_user_mutation] = lambda: Principal(
        user_id="user-1",
        subject="user-1",
        email="user@example.test",
        organization_id="organization-1",
        membership_id="membership-1",
    )
    runner = RetryableRunner()
    service = AnalysisRuntimeService(
        repository=InMemoryActivityRepository(), owner=Owner(), runner=runner
    )
    app.state.analysis_runtime = service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        started = await client.post(
            "/api/v1/threads/thread-1/runs", json={"message": "AAPL"}
        )
        source_run_id = started.json()["run_id"]
        task = service._tasks.get("thread-1")
        if task is not None:
            await task
        source = (
            await client.get(
                f"/api/v1/threads/thread-1/activities?run_id={source_run_id}"
            )
        ).json()
        checkpoint = source["failure"]["checkpoint"]
        path = f"/api/v1/threads/thread-1/runs/{source_run_id}/retry"
        missing_key = await client.post(
            path,
            json={"contract_version": "v1", "checkpoint": checkpoint},
        )
        first = await client.post(
            path,
            headers={"Idempotency-Key": "retry-http-1"},
            json={"contract_version": "v1", "checkpoint": checkpoint},
        )
        duplicate = await client.post(
            path,
            headers={"Idempotency-Key": "retry-http-1"},
            json={"contract_version": "v1", "checkpoint": checkpoint},
        )
        task = service._tasks.get("thread-1")
        if task is not None:
            await task

    assert missing_key.status_code == 422
    assert first.status_code == duplicate.status_code == 202
    first_payload = first.json()
    duplicate_payload = duplicate.json()
    for key in (
        "thread_id",
        "run_id",
        "retry_operation_id",
        "source_run_id",
        "checkpoint",
        "attempt",
    ):
        assert first_payload[key] == duplicate_payload[key]
    assert first_payload["source_run_id"] == source_run_id
    assert first_payload["run_id"] != source_run_id
    assert first_payload["checkpoint"] == checkpoint
    assert runner.calls == 2
    operation_schema = app.openapi()["components"]["schemas"]["RetryResponse"]
    assert "retry_operation_id" in operation_schema["properties"]
    snapshot_schema = app.openapi()["components"]["schemas"]["WorkflowSnapshot"]
    public_retry_schema = app.openapi()["components"]["schemas"]["RetryOperationView"]
    assert snapshot_schema["properties"]["retry_operation"]["anyOf"][0][
        "$ref"
    ].endswith("/RetryOperationView")
    assert not {"principal_id", "idempotency_key", "request_hash"}.intersection(
        public_retry_schema["properties"]
    )
