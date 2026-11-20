"""Synthetic policy/caller checks; real issuer acceptance is separate."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from threading import Event, Lock

import pytest
import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fundamental_service import app as app_module
from fundamental_service.app import create_app
from fundamental_service.app import _automatic_calculation_flight_key
from fundamental_service.application import service as service_module
from fundamental_service.application.service import FundamentalApplication
from fundamental_service import automatic_valuation as automatic_valuation_module
from fundamental_service.automatic_valuation import (
    automatic_approval_issues as _automatic_approval_issues,
)
from fundamental_service.calculator import calculate as calculate_raw
from fundamental_service.calculation_flights import (
    CalculationFlightRegistry,
    ImmutableCalculationResult,
)
from fundamental_service.automatic_approval import (
    AutomaticApprovalModelV1,
    AutomaticCallerGrantV1,
    AutomaticValuationApprovalPolicyV1,
)
from fundamental_service.automatic_valuation import (
    AutomaticValuationExecutor,
    AutomaticValuationRequestV1,
    load_runtime_automatic_approval_policy,
)
from fundamental_service.contracts import UncertaintyV1, ValuationEvidenceReadRequestV1
from fundamental_service.operations import ServiceError
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.testsupport import auth_headers, make_internal_envelope
from test_conditional_reinvestment_composer import _prepared


def _case(tmp_path, **policy_updates):
    fixture, _, candidate, prepared = _prepared(tmp_path)
    now = datetime.now(UTC)
    policy = AutomaticValuationApprovalPolicyV1(
        policy_id="local-research",
        policy_version="local-research-v1",
        effective_from=now - timedelta(days=1),
        expires_at=now + timedelta(days=1),
        callers=(
            AutomaticCallerGrantV1(
                caller_id="subject-test", organization_id="organization-test"
            ),
        ),
        models=(
            AutomaticApprovalModelV1(
                model_id=prepared.model_id,
                model_version=prepared.model_version,
                valuation_policy_version=prepared.policy_version,
            ),
        ),
        source_use_policy_digest=fixture.application.source_use_policy.digest,
        allow_provisional=True,
        allow_uncalibrated_what_if=True,
        allowed_issue_codes=tuple(sorted(set(prepared.issue_codes))),
        allowed_missing_evidence=tuple(sorted(set(prepared.missing_evidence))),
        limitations=("Synthetic local what-if; no calibrated estimate or bounds.",),
    )
    policy = AutomaticValuationApprovalPolicyV1.model_validate(
        policy.model_dump() | policy_updates
    )
    app = create_app(
        snapshot_repository=fixture.snapshots,
        fact_repository=fixture.facts,
        artifact_store=fixture.artifacts,
        metadata_store=fixture.metadata,
        config=fixture.application.config,
        policy_registry=fixture.application.policy_registry,
        source_use_policy=fixture.application.source_use_policy,
        automatic_approval_policy=policy,
    )
    request = {
        "preparation": ValuationEvidenceReadRequestV1(
            contract_version="fundamental.v1",
            snapshot_id=fixture.snapshot.snapshot_id,
            data_release_manifest_digest=candidate.manifest.manifest_digest,
            model_id="fcff_dcf",
        ).model_dump(mode="json"),
        "expected_input_digest": prepared.input.input_digest,
        "approval_policy_digest": policy.digest,
    }
    return fixture, TestClient(app), policy, request


def _execute(client, request):
    return client.post(
        "/v1/valuation/calculate-automatically",
        headers=auth_headers(),
        json=make_internal_envelope(request),
    )


def test_authenticated_policy_decision_executes_and_reuses_exact_evidence(
    tmp_path, monkeypatch
):
    fixture, client, policy, request = _case(tmp_path)
    original_calculate = service_module.calculate
    calculator_calls = 0

    def count_calculations(*args, **kwargs):
        nonlocal calculator_calls
        calculator_calls += 1
        return original_calculate(*args, **kwargs)

    monkeypatch.setattr(service_module, "calculate", count_calculations)
    first = _execute(client, request)
    assert first.status_code == 200, first.text
    result = first.json()["result"]
    decision = result["decision"]
    assert decision["decision"] == "approved"
    assert decision["caller_id"] == "subject-test"
    assert decision["policy_ref"]["content_hash"] == policy.digest
    assert decision["input_digest"] == request["expected_input_digest"]
    assert result["calculation"]["status"] == "provisional"
    assert len(result["calculation"]["scenario_results"]) == 3
    assert result["calculation"]["input_digest"] == decision["input_digest"]
    repeat = _execute(client, request)
    assert repeat.status_code == 200, repeat.text
    replay = repeat.json()["result"]
    assert calculator_calls == 2
    assert replay["calculation"] == result["calculation"]
    for name in (
        "policy_publication",
        "preparation_publication",
        "decision_publication",
        "execution_publication",
    ):
        assert result[name]["wrote"] is True
        assert replay[name]["wrote"] is False
        assert result[name]["artifact"] == replay[name]["artifact"]
        record = result[name]["artifact"]
        payload = fixture.artifacts.read(record["artifact_id"])
        assert sha256_digest(json.loads(payload)) == record["content_hash"]
    execution = json.loads(
        fixture.artifacts.read(
            result["execution_publication"]["artifact"]["artifact_id"]
        )
    )
    assert execution["approval_ref"]["content_hash"] == sha256_digest(decision)
    assert execution["result_digest"] == sha256_digest(result["calculation"])


@pytest.mark.parametrize(
    "updates,request_updates,code",
    [
        ({}, {"expected_input_digest": "a" * 64}, "INPUT_DIGEST_MISMATCH"),
        ({}, {"approval_policy_digest": "a" * 64}, "POLICY_MISMATCH"),
        ({"source_use_policy_digest": "a" * 64}, {}, "SOURCE_POLICY_MISMATCH"),
        ({"allowed_issue_codes": ()}, {}, "UNSUPPORTED_ISSUES"),
        ({"allowed_missing_evidence": ()}, {}, "UNSUPPORTED_MISSING_EVIDENCE"),
        ({"allow_uncalibrated_what_if": False}, {}, "WHAT_IF_NOT_AUTHORIZED"),
        (
            {"allow_uncalibrated_what_if": False, "allow_provisional": False},
            {},
            "QUALITY_NOT_AUTHORIZED",
        ),
        (
            {
                "callers": (
                    AutomaticCallerGrantV1(
                        caller_id="another-caller", organization_id="organization-test"
                    ),
                )
            },
            {},
            "CALLER_NOT_AUTHORIZED",
        ),
        (
            {
                "effective_from": datetime(2025, 1, 1, tzinfo=UTC),
                "expires_at": datetime(2025, 2, 1, tzinfo=UTC),
            },
            {},
            "POLICY_NOT_EFFECTIVE",
        ),
    ],
)
def test_refusal_is_retained_and_never_enters_calculator(
    tmp_path, monkeypatch, updates, request_updates, code
):
    fixture, client, _, request = _case(tmp_path, **updates)

    def forbidden(*args, **kwargs):
        raise AssertionError("refused policy entered calculator")

    monkeypatch.setattr(FundamentalApplication, "_calculate_resolved", forbidden)
    response = _execute(client, request | request_updates)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["decision"]["decision"] == "rejected"
    assert any(item.endswith(code) for item in result["decision"]["issue_codes"])
    assert result["calculation"] is result["execution_publication"] is None
    stored = fixture.artifacts.read(
        result["decision_publication"]["artifact"]["artifact_id"]
    )
    assert stored == canonical_bytes(result["decision"])


def test_automatic_route_requires_signed_context_and_rejects_supplied_approval(
    tmp_path,
):
    _, client, _, request = _case(tmp_path)
    unsigned = client.post(
        "/v1/valuation/calculate-automatically", json=make_internal_envelope(request)
    )
    assert unsigned.status_code == 401
    spoofed = _execute(client, request | {"caller_id": "subject-test"})
    assert spoofed.status_code == 400
    bypass = _execute(client, request | {"caller_approval": {"decision": "approved"}})
    assert bypass.status_code == 400


def test_missing_deployment_authorization_never_calculates(tmp_path):
    fixture, _, _, request = _case(tmp_path)
    with pytest.raises(ServiceError) as error:
        AutomaticValuationExecutor(fixture.application, None).execute(
            AutomaticValuationRequestV1.model_validate_json(canonical_bytes(request)),
            caller_id="subject-test",
            organization_id="organization-test",
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        )
    assert error.value.code == "AUTOMATIC_APPROVAL_NOT_CONFIGURED"


def test_corrupted_decision_refuses_reuse_before_calculator(tmp_path, monkeypatch):
    fixture, client, _, request = _case(tmp_path)
    response = _execute(client, request)
    assert response.status_code == 200, response.text
    record = response.json()["result"]["decision_publication"]["artifact"]
    path = fixture.artifacts._artifact_path(
        record["content_hash"], record["media_type"]
    )
    path.write_bytes(b"corrupted retained approval")

    def forbidden(*args, **kwargs):
        raise AssertionError("corrupted decision entered calculator")

    monkeypatch.setattr(FundamentalApplication, "_calculate_resolved", forbidden)
    repeated = _execute(client, request)
    assert repeated.status_code == 422, repeated.text
    assert repeated.json()["error"]["code"] == "ARTIFACT_BYTES_UNAVAILABLE"


def test_changed_result_cannot_reuse_execution_publication(tmp_path):
    from fundamental_service.automatic_valuation import AutomaticValuationResponseV1

    _, client, _, request = _case(tmp_path)
    response = _execute(client, request)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    result["calculation"]["base"]["per_share_value"] = "0.0001"
    with pytest.raises(ValidationError, match="execution publication content differs"):
        AutomaticValuationResponseV1.model_validate_json(canonical_bytes(result))


def test_deployment_requires_complete_exact_pin_and_valid_policy(tmp_path, monkeypatch):
    _, _, policy, _ = _case(tmp_path)
    monkeypatch.delenv("FUNDAMENTAL_AUTOMATIC_APPROVAL_POLICY_FILE", raising=False)
    monkeypatch.delenv("FUNDAMENTAL_AUTOMATIC_APPROVAL_POLICY_DIGEST", raising=False)
    assert load_runtime_automatic_approval_policy() is None
    path = tmp_path / "approval.json"
    path.write_bytes(canonical_bytes(policy))
    monkeypatch.setenv("FUNDAMENTAL_AUTOMATIC_APPROVAL_POLICY_FILE", str(path))
    with pytest.raises(ValueError, match="file and digest"):
        load_runtime_automatic_approval_policy()
    monkeypatch.setenv("FUNDAMENTAL_AUTOMATIC_APPROVAL_POLICY_DIGEST", "a" * 64)
    with pytest.raises(ValueError, match="digest differs"):
        load_runtime_automatic_approval_policy()
    monkeypatch.setenv("FUNDAMENTAL_AUTOMATIC_APPROVAL_POLICY_DIGEST", policy.digest)
    assert load_runtime_automatic_approval_policy() == policy
    with pytest.raises(ValidationError, match="timezone"):
        AutomaticValuationApprovalPolicyV1.model_validate(
            policy.model_dump() | {"effective_from": datetime(2025, 1, 1)}
        )


def test_calculation_flight_key_binds_full_request_and_authority(tmp_path):
    _, _, policy, raw_request = _case(tmp_path)
    request = AutomaticValuationRequestV1.model_validate(raw_request)
    common = {
        "caller_id": "subject-test",
        "organization_id": "organization-test",
        "automatic_policy_digest": policy.digest,
        "source_use_policy_digest": "b" * 64,
        "runtime_identity": "runtime-one",
    }
    baseline = _automatic_calculation_flight_key(request, **common)
    assert _automatic_calculation_flight_key(request, **common) == baseline
    assert (
        _automatic_calculation_flight_key(
            request, **(common | {"caller_id": "other-caller"})
        )
        != baseline
    )
    assert (
        _automatic_calculation_flight_key(
            request, **(common | {"organization_id": "other-organization"})
        )
        != baseline
    )
    assert (
        _automatic_calculation_flight_key(
            request, **(common | {"automatic_policy_digest": "c" * 64})
        )
        != baseline
    )
    assert (
        _automatic_calculation_flight_key(
            request, **(common | {"source_use_policy_digest": "d" * 64})
        )
        != baseline
    )
    assert (
        _automatic_calculation_flight_key(
            request, **(common | {"runtime_identity": "runtime-two"})
        )
        != baseline
    )
    assert (
        _automatic_calculation_flight_key(
            request.model_copy(update={"expected_input_digest": "e" * 64}),
            **common,
        )
        != baseline
    )
    changed_preparation = request.preparation.model_copy(
        update={"model_id": "transition_fcff_dcf"}
    )
    assert (
        _automatic_calculation_flight_key(
            request.model_copy(update={"preparation": changed_preparation}),
            **common,
        )
        != baseline
    )


def test_concurrent_identical_automatic_requests_share_only_calculator_output(
    tmp_path, monkeypatch
):
    _, sync_client, _, request = _case(tmp_path)
    app = sync_client.app
    release_calculator = Event()
    calculator_started = Event()
    follower_joined = Event()
    count_lock = Lock()
    counts = {"prepare": 0, "policy": 0, "resolved": 0, "calculate": 0}

    original_prepare = FundamentalApplication.prepare_valuation_operation
    original_resolved = FundamentalApplication._calculate_resolved
    original_calculate = service_module.calculate

    def increment(name):
        with count_lock:
            counts[name] += 1

    def prepare(self, *args, **kwargs):
        increment("prepare")
        return original_prepare(self, *args, **kwargs)

    def resolved(self, *args, **kwargs):
        increment("resolved")
        return original_resolved(self, *args, **kwargs)

    def calculate(*args, **kwargs):
        increment("calculate")
        calculator_started.set()
        assert release_calculator.wait(5), "test did not release calculator"
        return original_calculate(*args, **kwargs)

    def issues(*args, **kwargs):
        increment("policy")
        return _automatic_approval_issues(*args, **kwargs)

    monkeypatch.setattr(FundamentalApplication, "prepare_valuation_operation", prepare)
    monkeypatch.setattr(FundamentalApplication, "_calculate_resolved", resolved)
    monkeypatch.setattr(service_module, "calculate", calculate)
    monkeypatch.setattr(automatic_valuation_module, "automatic_approval_issues", issues)
    registry = app.state.calculation_flights
    original_join = registry.join

    def join(key):
        lease = original_join(key)
        if lease is not None and not lease.is_owner:
            follower_joined.set()
        return lease

    monkeypatch.setattr(registry, "join", join)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://service"
        ) as client:
            first = asyncio.create_task(
                client.post(
                    "/v1/valuation/calculate-automatically",
                    headers=auth_headers(),
                    json=make_internal_envelope(
                        request, correlation_id="singleflight-owner"
                    ),
                )
            )
            assert await asyncio.to_thread(calculator_started.wait, 3)
            second = asyncio.create_task(
                client.post(
                    "/v1/valuation/calculate-automatically",
                    headers=auth_headers(),
                    json=make_internal_envelope(
                        request, correlation_id="singleflight-follower"
                    ),
                )
            )
            try:
                assert await asyncio.to_thread(follower_joined.wait, 3)
            finally:
                release_calculator.set()
            return await asyncio.gather(first, second)

    responses = asyncio.run(exercise())
    assert [response.status_code for response in responses] == [200, 200], [
        response.text for response in responses
    ]
    results = [response.json()["result"] for response in responses]
    assert results[0]["calculation"] == results[1]["calculation"]
    assert results[0]["decision"]["caller_id"] == results[1]["decision"]["caller_id"]
    assert counts == {"prepare": 2, "policy": 2, "resolved": 2, "calculate": 1}
    for name in (
        "policy_publication",
        "preparation_publication",
        "decision_publication",
        "execution_publication",
    ):
        assert results[0][name]["artifact"] == results[1][name]["artifact"]
        assert results[0][name]["wrote"] is True
        assert results[1][name]["wrote"] is False


def test_follower_rechecks_policy_after_waiting_for_shared_calculation(
    tmp_path, monkeypatch
):
    initial_time = datetime.now(UTC)
    expires_at = initial_time + timedelta(seconds=10)
    _, sync_client, _, request = _case(tmp_path, expires_at=expires_at)
    app = sync_client.app
    release_calculator = Event()
    calculator_started = Event()
    follower_joined = Event()
    policy_checks = 0
    calculator_calls = 0

    class Clock:
        current = initial_time

        @classmethod
        def now(cls, tz=None):
            return cls.current

    original_calculate = service_module.calculate
    original_issues = automatic_valuation_module.automatic_approval_issues
    original_join = app.state.calculation_flights.join

    def calculate(*args, **kwargs):
        nonlocal calculator_calls
        calculator_calls += 1
        calculator_started.set()
        assert release_calculator.wait(5), "test did not release calculator"
        return original_calculate(*args, **kwargs)

    def issues(*args, **kwargs):
        nonlocal policy_checks
        policy_checks += 1
        return original_issues(*args, **kwargs)

    def join(key):
        lease = original_join(key)
        if lease is not None and not lease.is_owner:
            follower_joined.set()
        return lease

    monkeypatch.setattr(service_module, "calculate", calculate)
    monkeypatch.setattr(automatic_valuation_module, "automatic_approval_issues", issues)
    monkeypatch.setattr(automatic_valuation_module, "datetime", Clock)
    monkeypatch.setattr(app.state.calculation_flights, "join", join)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://service"
        ) as client:
            first = asyncio.create_task(
                client.post(
                    "/v1/valuation/calculate-automatically",
                    headers=auth_headers(),
                    json=make_internal_envelope(
                        request, correlation_id="policy-flight-owner"
                    ),
                )
            )
            assert await asyncio.to_thread(calculator_started.wait, 3)
            second = asyncio.create_task(
                client.post(
                    "/v1/valuation/calculate-automatically",
                    headers=auth_headers(),
                    json=make_internal_envelope(
                        request, correlation_id="policy-flight-follower"
                    ),
                )
            )
            try:
                assert await asyncio.to_thread(follower_joined.wait, 3)
            finally:
                Clock.current = expires_at + timedelta(seconds=1)
                release_calculator.set()
            return await asyncio.gather(first, second)

    responses = asyncio.run(exercise())
    assert [response.status_code for response in responses] == [200, 200], [
        response.text for response in responses
    ]
    owner_result = responses[0].json()["result"]
    follower_result = responses[1].json()["result"]
    assert owner_result["decision"]["decision"] == "approved"
    assert follower_result["decision"]["decision"] == "rejected"
    assert (
        "AUTOMATIC_APPROVAL_POLICY_NOT_EFFECTIVE"
        in follower_result["decision"]["issue_codes"]
    )
    assert follower_result["calculation"] is None
    assert follower_result["execution_publication"] is None
    assert policy_checks == 2
    assert calculator_calls == 1


def test_http_follower_deadline_detaches_without_cancelling_owner(
    tmp_path, monkeypatch
):
    _, sync_client, _, request = _case(tmp_path)
    app = sync_client.app
    release_calculator = Event()
    calculator_started = Event()
    follower_joined = Event()
    calculator_calls = 0
    original_calculate = service_module.calculate
    original_join = app.state.calculation_flights.join

    def calculate(*args, **kwargs):
        nonlocal calculator_calls
        calculator_calls += 1
        calculator_started.set()
        assert release_calculator.wait(5), "test did not release calculator"
        return original_calculate(*args, **kwargs)

    def join(key):
        lease = original_join(key)
        if lease is not None and not lease.is_owner:
            follower_joined.set()
        return lease

    monkeypatch.setattr(service_module, "calculate", calculate)
    monkeypatch.setattr(app.state.calculation_flights, "join", join)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://service"
        ) as client:
            owner = asyncio.create_task(
                client.post(
                    "/v1/valuation/calculate-automatically",
                    headers=auth_headers(),
                    json=make_internal_envelope(
                        request, correlation_id="deadline-flight-owner"
                    ),
                )
            )
            assert await asyncio.to_thread(calculator_started.wait, 3)
            follower = asyncio.create_task(
                client.post(
                    "/v1/valuation/calculate-automatically",
                    headers=auth_headers(),
                    json=make_internal_envelope(
                        request,
                        correlation_id="deadline-flight-follower",
                        deadline_at=datetime.now(UTC) + timedelta(milliseconds=100),
                    ),
                )
            )
            try:
                assert await asyncio.to_thread(follower_joined.wait, 3)
                timed_out = await asyncio.wait_for(follower, 2)
                assert timed_out.status_code == 408, timed_out.text
                assert timed_out.json()["error"]["code"] == (
                    "REQUEST_DEADLINE_EXCEEDED"
                )
                assert not owner.done()
            finally:
                release_calculator.set()
            completed = await owner
            return timed_out, completed

    timed_out, completed = asyncio.run(exercise())
    assert timed_out.status_code == 408
    assert completed.status_code == 200, completed.text
    assert calculator_calls == 1


def test_flight_registry_bounds_waiters_and_drops_completed_results():
    registry = CalculationFlightRegistry(
        max_active_flights=1, max_participants_per_flight=2
    )
    owner = registry.join("exact-input")
    assert owner is not None and owner.is_owner
    follower = registry.join("exact-input")
    assert follower is not None and not follower.is_owner
    assert registry.join("exact-input") is None
    assert registry.join("other-input") is None

    owner.close()

    async def receive_no_result():
        result = await follower.wait(datetime.now(UTC) + timedelta(seconds=1))
        follower.close()
        return result

    assert asyncio.run(receive_no_result()) is None
    next_owner = registry.join("exact-input")
    assert next_owner is not None and next_owner.is_owner
    next_owner.close()


def test_immutable_calculation_result_checks_identity_and_rehydrates_fresh_model(
    tmp_path,
):
    _, _, _, preparation = _prepared(tmp_path)
    value = preparation.input
    assert value is not None
    calculation_input = value.model_copy(
        update={
            "uncertainty": UncertaintyV1(mode="none"),
            "input_digest": None,
            "caller_approval": None,
        }
    ).with_digest()
    result = calculate_raw(calculation_input, allow_provisional=True)
    shared = ImmutableCalculationResult.capture(
        calculation_input, allow_provisional=True, artifact=result
    )

    reused = shared.materialize(calculation_input, allow_provisional=True)
    assert reused == result
    assert reused is not result
    assert shared.materialize(calculation_input, allow_provisional=False) is None

    changed = calculation_input.model_copy(
        update={"historical_facts": (*value.historical_facts, "changed-fact")}
    ).with_digest()
    assert shared.materialize(changed, allow_provisional=True) is None

    corrupted = ImmutableCalculationResult(
        input_digest=shared.input_digest,
        semantics_digest=shared.semantics_digest,
        artifact_bytes=b"invalid calculation bytes",
    )
    assert corrupted.materialize(calculation_input, allow_provisional=True) is None


def test_follower_timeout_detaches_without_cancelling_owner(tmp_path):
    _, _, _, preparation = _prepared(tmp_path)
    value = preparation.input
    assert value is not None
    calculation_input = value.model_copy(
        update={
            "uncertainty": UncertaintyV1(mode="none"),
            "input_digest": None,
            "caller_approval": None,
        }
    ).with_digest()
    result = calculate_raw(calculation_input, allow_provisional=True)
    registry = CalculationFlightRegistry()
    owner = registry.join("exact-input")
    follower = registry.join("exact-input")
    assert owner is not None and owner.is_owner
    assert follower is not None and not follower.is_owner

    async def expire_follower():
        with pytest.raises(ServiceError) as error:
            await follower.wait(datetime.now(UTC) + timedelta(milliseconds=20))
        assert error.value.code == "REQUEST_DEADLINE_EXCEEDED"
        follower.close()

    asyncio.run(expire_follower())

    # The owner can still finish; with no attached waiters the result is discarded.
    owner.publish(
        result, calculation_input, True, datetime.now(UTC) + timedelta(seconds=1)
    )
    owner.close()
    next_owner = registry.join("exact-input")
    assert next_owner is not None and next_owner.is_owner
    next_owner.close()


def test_waiter_retention_remains_bounded_after_owner_publishes(tmp_path):
    _, _, _, preparation = _prepared(tmp_path)
    value = preparation.input
    assert value is not None
    calculation_input = value.model_copy(
        update={
            "uncertainty": UncertaintyV1(mode="none"),
            "input_digest": None,
            "caller_approval": None,
        }
    ).with_digest()
    result = calculate_raw(calculation_input, allow_provisional=True)
    registry = CalculationFlightRegistry(
        max_active_flights=1,
        max_participants_per_flight=2,
        max_active_participants=2,
    )
    owner = registry.join("exact-input")
    follower = registry.join("exact-input")
    assert owner is not None and owner.is_owner
    assert follower is not None and not follower.is_owner

    owner.publish(
        result, calculation_input, True, datetime.now(UTC) + timedelta(seconds=1)
    )
    # Publication removes the completed key, but attached waiters still hold the
    # immutable bytes. The total participant bound includes those references.
    assert registry.join("other-input") is None

    async def receive_result():
        shared = await follower.wait(datetime.now(UTC) + timedelta(seconds=1))
        assert shared is not None
        follower.close()

    asyncio.run(receive_result())
    owner.close()
    next_owner = registry.join("other-input")
    assert next_owner is not None and next_owner.is_owner
    next_owner.close()


def test_saturated_automatic_admission_rejects_before_worker_queue(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        app_module,
        "CalculationFlightRegistry",
        lambda: CalculationFlightRegistry(
            max_active_flights=1,
            max_participants_per_flight=1,
            max_active_participants=1,
        ),
    )
    _, sync_client, policy, raw_request = _case(tmp_path)
    app = sync_client.app
    registry = app.state.calculation_flights
    source_policy = app.state.application.source_use_policy
    assert source_policy is not None
    request = AutomaticValuationRequestV1.model_validate(raw_request)
    key = _automatic_calculation_flight_key(
        request,
        caller_id="subject-test",
        organization_id="organization-test",
        automatic_policy_digest=policy.digest,
        source_use_policy_digest=source_policy.digest,
        runtime_identity=registry.runtime_identity,
    )
    reservation = registry.join(key)
    assert reservation is not None and reservation.is_owner
    worker_entered = False

    def forbidden(*args, **kwargs):
        nonlocal worker_entered
        worker_entered = True
        raise AssertionError("saturated request entered the valuation worker")

    monkeypatch.setattr(AutomaticValuationExecutor, "execute", forbidden)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://service"
        ) as client:
            return await client.post(
                "/v1/valuation/calculate-automatically",
                headers=auth_headers(),
                json=make_internal_envelope(
                    raw_request, correlation_id="singleflight-over-capacity"
                ),
            )

    try:
        response = asyncio.run(exercise())
    finally:
        reservation.close()
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == ("AUTOMATIC_VALUATION_CAPACITY_EXCEEDED")
    assert worker_entered is False
