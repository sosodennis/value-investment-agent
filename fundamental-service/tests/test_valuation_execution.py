"""Execution budgets protect the event loop and prevent late calculation writes."""

import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event

import httpx
import pytest

from fundamental_service.app import create_app
from fundamental_service.application.service import FundamentalApplication
from fundamental_service.operations import ServiceError
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
