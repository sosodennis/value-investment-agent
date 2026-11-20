"""Execution budgets protect the event loop and prevent late calculation writes."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event

import httpx
import pytest

from fundamental_service.app import create_app
from fundamental_service.application.service import FundamentalApplication
from fundamental_service.interface import transport
from fundamental_service.operations import (
    OperationsConfig,
    ServiceError,
)
from fundamental_service.testsupport import (
    auth_headers,
    make_internal_envelope,
    make_valuation,
)
from test_api import (
    _FactRepository,
    _SnapshotRepository,
    _bind_initial_policy,
    _with_uncertainty_digest,
)
from test_valuation_diagnostics import wait_for_diagnostics


@pytest.mark.parametrize(
    "route,method",
    [
        ("prepare", "prepare_valuation"),
        ("calculate", "calculate_valuation"),
        ("calculate-with-policy", "calculate_with_policy"),
        ("uncertainty", "uncertainty_valuation"),
    ],
)
def test_valuation_worker_preserves_health_and_expires_queued_work(
    monkeypatch, route, method
):
    started, release = Event(), Event()
    executed = []

    def execute(self, value, *, deadline_at, **kwargs):
        executed.append(value)
        started.set()
        assert release.wait(5), "test did not release the valuation worker"
        return {"completed": True}

    monkeypatch.setattr(FundamentalApplication, method, execute)
    payload = _bind_initial_policy(make_valuation()).model_dump(mode="json")
    if route == "prepare":
        payload = {
            "contract_version": "fundamental.v1",
            "snapshot_id": "snapshot-1",
            "data_release_manifest_digest": "a" * 64,
            "model_id": "fcff_dcf",
        }
    elif route == "uncertainty":
        payload = _with_uncertainty_digest(payload).model_dump(mode="json")
    app = create_app()

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://service"
        ) as client:
            first = asyncio.create_task(
                client.post(
                    f"/v1/valuation/{route}",
                    headers=auth_headers(),
                    json=make_internal_envelope(payload),
                )
            )
            try:
                assert await asyncio.to_thread(started.wait, 2), "worker did not start"
                health = await asyncio.wait_for(client.get("/livez"), 1)
                assert health.status_code == 200
                queued = await asyncio.wait_for(
                    client.post(
                        f"/v1/valuation/{route}",
                        headers=auth_headers(),
                        json=make_internal_envelope(
                            payload,
                            deadline_at=datetime.now(UTC) + timedelta(milliseconds=100),
                        ),
                    ),
                    1,
                )
                assert queued.status_code == 408, queued.text
                assert queued.json()["error"]["code"] == "REQUEST_DEADLINE_EXCEEDED"
                assert len(executed) == 1
            finally:
                release.set()
                completed = await first
            assert completed.status_code == 200, completed.text
            # An expired waiter must neither execute later nor leak the only slot.
            repeated = await client.post(
                f"/v1/valuation/{route}",
                headers=auth_headers(),
                json=make_internal_envelope(payload),
            )
            assert repeated.status_code == 200, repeated.text
            assert len(executed) == 2

    asyncio.run(exercise())


@pytest.mark.parametrize("diagnostics_enabled", [False, True])
def test_valuation_diagnostic_records_queue_worker_deadline_without_body(
    monkeypatch, caplog, diagnostics_enabled
):
    started, release = Event(), Event()

    def execute(self, value, *, deadline_at, **kwargs):
        started.set()
        assert release.wait(5), "test did not release the valuation worker"
        return {"completed": True}

    monkeypatch.setattr(FundamentalApplication, "uncertainty_valuation", execute)
    payload = _with_uncertainty_digest(
        _bind_initial_policy(make_valuation()).model_dump(mode="json")
    ).model_dump(mode="json")
    app = create_app(
        config=OperationsConfig.testing(valuation_diagnostics=diagnostics_enabled)
    )
    digested_lengths = []

    def track_response_digest(body):
        digested_lengths.append(len(body))
        return sha256(body)

    monkeypatch.setattr(transport, "sha256", track_response_digest)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://service"
        ) as client:
            first = asyncio.create_task(
                client.post(
                    "/v1/valuation/uncertainty",
                    headers=auth_headers(),
                    json=make_internal_envelope(payload, correlation_id="trace-first"),
                )
            )
            try:
                assert await asyncio.to_thread(started.wait, 2), "worker did not start"
                queued = await asyncio.wait_for(
                    client.post(
                        "/v1/valuation/uncertainty",
                        headers=auth_headers(),
                        json=make_internal_envelope(
                            payload,
                            correlation_id="trace-second",
                            deadline_at=datetime.now(UTC) + timedelta(milliseconds=100),
                        ),
                    ),
                    1,
                )
            finally:
                release.set()
                completed = await first
            assert queued.status_code == 408, queued.text
            assert completed.status_code == 200, completed.text
            return completed, queued

    with caplog.at_level("INFO", logger="fundamental_service"):
        try:
            completed, queued = asyncio.run(exercise())
            wait_for_diagnostics(app.state.valuation_diagnostic_sink)
        finally:
            app.state.valuation_diagnostic_sink.close()

    events = []
    for record in caplog.records:
        if record.getMessage().startswith("fundamental_valuation_diagnostic "):
            events.append(json.loads(record.getMessage().split(" ", 1)[1]))
    if not diagnostics_enabled:
        assert events == []
        assert digested_lengths == []
        return

    assert digested_lengths == [len(queued.content), len(completed.content)]
    response_log_ids = {
        record.status_code: record.request_log_id
        for record in caplog.records
        if record.getMessage() == "fundamental_request"
        and record.route_template == "/v1/valuation/uncertainty"
    }
    assert {200, 408} <= response_log_ids.keys()
    by_request_id = {
        status_code: [
            item for item in events if item["request_log_id"] == request_log_id
        ]
        for status_code, request_log_id in response_log_ids.items()
    }
    first_events = {item["event"] for item in by_request_id[200]}
    second_events = {item["event"] for item in by_request_id[408]}
    assert {
        "request_admitted",
        "queue_wait_started",
        "worker_acquired",
        "execution_started",
        "execution_finished",
        "response_emitted",
    } <= first_events
    assert {
        "request_admitted",
        "queue_wait_started",
        "deadline_expired",
        "response_emitted",
    } <= (second_events)
    first_admitted = next(
        item for item in by_request_id[200] if item["event"] == "request_admitted"
    )
    second_admitted = next(
        item for item in by_request_id[408] if item["event"] == "request_admitted"
    )
    assert first_admitted["request_log_id"] == response_log_ids[200]
    assert second_admitted["request_log_id"] == response_log_ids[408]
    assert first_admitted["request_log_id"] != second_admitted["request_log_id"]
    assert first_admitted["route_template"] == "/v1/valuation/uncertainty"
    assert second_admitted["route_template"] == "/v1/valuation/uncertainty"
    assert (
        not {
            "caller_id",
            "organization_id",
            "input_identity",
        }
        & first_admitted.keys()
    )
    assert (
        not {
            "caller_id",
            "organization_id",
            "input_identity",
        }
        & second_admitted.keys()
    )
    assert "trace-first" not in caplog.text
    assert "trace-second" not in caplog.text
    completed_response = next(
        item for item in by_request_id[200] if item["event"] == "response_emitted"
    )
    assert completed_response["status_code"] == 200
    assert completed_response["route_template"] == "/v1/valuation/uncertainty"
    assert completed_response["response_body_length"] == len(completed.content)
    assert (
        completed_response["response_body_sha256"]
        == sha256(completed.content).hexdigest()
    )
    assert "response_body" not in completed_response
    assert "completed" not in json.dumps(completed_response)
    assert "error_message" not in completed_response
    failed_response = next(
        item for item in by_request_id[408] if item["event"] == "response_emitted"
    )
    assert failed_response["status_code"] == 408
    assert failed_response["route_template"] == "/v1/valuation/uncertainty"
    assert failed_response["response_body_length"] == len(queued.content)
    assert failed_response["response_body_sha256"] == sha256(queued.content).hexdigest()
    assert failed_response["error_code"] == "REQUEST_DEADLINE_EXCEEDED"
    assert "response_body" not in failed_response
    assert "error_message" not in failed_response
    assert queued.json()["error"]["message"] not in json.dumps(failed_response)
    assert "trace-first" not in caplog.text
    assert "trace-second" not in caplog.text
    timeout = next(
        item for item in by_request_id[408] if item["event"] == "deadline_expired"
    )
    assert timeout["timeout_phase"] == "queue_wait"
    assert all(item["deadline_at"] is not None for item in events)


@pytest.mark.parametrize("expired_stage", ["sources", "composition", "calculator"])
def test_expired_stage_never_enters_next_calculation_or_persistence(
    monkeypatch, expired_stage
):
    import fundamental_service.application.service as service_module
    import fundamental_service.operations as operations

    now = datetime.now(UTC)
    expired = False

    class Clock:
        @staticmethod
        def now(tz):
            return now + timedelta(seconds=2) if expired else now

    monkeypatch.setattr(operations, "datetime", Clock)
    application = create_app(
        _SnapshotRepository(), fact_repository=_FactRepository()
    ).state.application
    value = _bind_initial_policy(make_valuation())
    visited = []

    def stage(name, original):
        def run(*args, **kwargs):
            nonlocal expired
            visited.append(name)
            result = original(*args, **kwargs)
            if name == expired_stage:
                expired = True
            return result

        return run

    monkeypatch.setattr(
        FundamentalApplication,
        "_verify_fact_references",
        stage("sources", FundamentalApplication._verify_fact_references),
    )
    monkeypatch.setattr(
        FundamentalApplication,
        "_is_released_conditional_input",
        stage("composition", FundamentalApplication._is_released_conditional_input),
    )
    monkeypatch.setattr(
        service_module, "calculate", stage("calculator", service_module.calculate)
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("expired calculation reached persistence")

    monkeypatch.setattr(FundamentalApplication, "_persist_evidence", forbidden)
    with pytest.raises(ServiceError) as error:
        application.calculate_valuation(
            value,
            correlation_id="deadline-test",
            deadline_at=now + timedelta(seconds=1),
        )
    assert error.value.code == "REQUEST_DEADLINE_EXCEEDED"
    assert (
        visited
        == ["sources", "composition", "calculator"][
            : ["sources", "composition", "calculator"].index(expired_stage) + 1
        ]
    )
