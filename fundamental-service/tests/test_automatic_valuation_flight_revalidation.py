"""Flight followers recheck source permission before automatic approval."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from threading import Event, Lock
from time import sleep

import httpx
import pytest
from fastapi.testclient import TestClient
from fundamental_service import automatic_valuation as automatic_valuation_module
from fundamental_service.app import create_app
from fundamental_service.application import service as service_module
from fundamental_service.application.service import FundamentalApplication
from fundamental_service.automatic_approval import (
    AutomaticApprovalModelV1,
    AutomaticCallerGrantV1,
    AutomaticValuationApprovalPolicyV1,
)
from fundamental_service.automatic_valuation import AutomaticValuationExecutor
from fundamental_service.calculation_flights import (
    ImmutableAutomaticValuationPreparation,
)
from fundamental_service.contracts import ValuationEvidenceReadRequestV1
from fundamental_service.testsupport import auth_headers, make_internal_envelope
from fundamental_service.valuation_preparation import AutomaticValuationPreparationV1
from test_automatic_valuation import _case
from test_preparation_runner import _reviewed_candidate
from test_valuation_release_inputs import _client, _prepare, _valuation_fixture


def _dilution_case(tmp_path):
    fixture = _valuation_fixture(tmp_path)
    candidate, canary = _reviewed_candidate(fixture)
    canary.validate(candidate.manifest, candidate.verification)
    preparation_client = _client(fixture)
    response = _prepare(preparation_client, fixture, candidate)
    assert response.status_code == 200, response.text
    preparation = AutomaticValuationPreparationV1.model_validate_json(
        json.dumps(response.json()["result"])
    )
    assert preparation.input is not None
    assert not candidate.manifest.conditional_capital_policies

    now = datetime.now(UTC)
    source_policy = fixture.application.source_use_policy
    assert source_policy is not None
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
                model_id=preparation.model_id,
                model_version=preparation.model_version,
                valuation_policy_version=preparation.policy_version,
            ),
        ),
        source_use_policy_digest=source_policy.digest,
        allow_provisional=True,
        allow_uncalibrated_what_if=True,
        allowed_issue_codes=tuple(sorted(set(preparation.issue_codes))),
        allowed_missing_evidence=tuple(sorted(set(preparation.missing_evidence))),
        limitations=("Synthetic local what-if; no calibrated estimate or bounds.",),
    )
    client = TestClient(
        create_app(
            snapshot_repository=fixture.snapshots,
            fact_repository=fixture.facts,
            artifact_store=fixture.artifacts,
            metadata_store=fixture.metadata,
            config=fixture.application.config,
            policy_registry=fixture.application.policy_registry,
            source_use_policy=source_policy,
            automatic_approval_policy=policy,
        )
    )
    request = {
        "preparation": ValuationEvidenceReadRequestV1(
            contract_version="fundamental.v1",
            snapshot_id=fixture.snapshot.snapshot_id,
            data_release_manifest_digest=candidate.manifest.manifest_digest,
            model_id=preparation.model_id,
        ).model_dump(mode="json"),
        "expected_input_digest": preparation.input.input_digest,
        "approval_policy_digest": policy.digest,
    }
    return fixture, client, request


def test_follower_quote_permission_refusal_precedes_approval_and_execution(
    tmp_path, monkeypatch
):
    _, client, _, request = _case(tmp_path)
    app = client.app
    release_preparation = Event()
    preparation_started = Event()
    follower_joined = Event()
    counter_lock = Lock()
    loader_calls = 0
    publication_calls = 0
    policy_checks = 0
    calculator_calls = 0
    original_prepare = FundamentalApplication.prepare_valuation_operation
    original_join = app.state.automatic_valuation_flights.join
    original_publish = AutomaticValuationExecutor._publish
    original_issues = automatic_valuation_module.automatic_approval_issues
    original_calculate = service_module.calculate
    original_loader = service_module.load_release_conditional_quote

    def reject_follower(*args, **kwargs):
        nonlocal loader_calls
        with counter_lock:
            loader_calls += 1
            call_number = loader_calls
        if call_number == 2:
            raise service_module.DilutionError(
                "DILUTION_QUOTE_ADMISSION_REFUSED", "quote permission was revoked"
            )
        return original_loader(*args, **kwargs)

    def prepare(self, *args, **kwargs):
        operation = original_prepare(self, *args, **kwargs)
        preparation_started.set()
        assert release_preparation.wait(5), "test did not release preparation"
        return operation

    def join(key):
        lease = original_join(key)
        if lease is not None and not lease.is_owner:
            follower_joined.set()
        return lease

    def publish(self, *args, **kwargs):
        nonlocal publication_calls
        with counter_lock:
            publication_calls += 1
        return original_publish(self, *args, **kwargs)

    def issues(*args, **kwargs):
        nonlocal policy_checks
        with counter_lock:
            policy_checks += 1
        return original_issues(*args, **kwargs)

    def calculate(*args, **kwargs):
        nonlocal calculator_calls
        with counter_lock:
            calculator_calls += 1
        return original_calculate(*args, **kwargs)

    monkeypatch.setattr(
        service_module, "load_release_conditional_quote", reject_follower
    )
    monkeypatch.setattr(FundamentalApplication, "prepare_valuation_operation", prepare)
    monkeypatch.setattr(app.state.automatic_valuation_flights, "join", join)
    monkeypatch.setattr(AutomaticValuationExecutor, "_publish", publish)
    monkeypatch.setattr(automatic_valuation_module, "automatic_approval_issues", issues)
    monkeypatch.setattr(service_module, "calculate", calculate)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://service"
        ) as http:
            owner = asyncio.create_task(
                http.post(
                    "/v1/valuation/calculate-automatically",
                    headers=auth_headers(),
                    json=make_internal_envelope(
                        request, correlation_id="conditional-flight-owner"
                    ),
                )
            )
            assert await asyncio.to_thread(preparation_started.wait, 3)
            follower = asyncio.create_task(
                http.post(
                    "/v1/valuation/calculate-automatically",
                    headers=auth_headers(),
                    json=make_internal_envelope(
                        request, correlation_id="conditional-flight-follower"
                    ),
                )
            )
            assert await asyncio.to_thread(follower_joined.wait, 3)
            release_preparation.set()
            return await asyncio.gather(owner, follower)

    owner_response, follower_response = asyncio.run(exercise())
    assert owner_response.status_code == 200, owner_response.text
    assert follower_response.status_code == 422, follower_response.text
    assert follower_response.json()["error"]["code"] == (
        "DILUTION_QUOTE_ADMISSION_REFUSED"
    )
    assert "result" not in follower_response.json()
    assert loader_calls == 2
    assert policy_checks == 1
    assert calculator_calls == 1, owner_response.text
    assert publication_calls == 4


def test_dilution_quote_permission_is_rechecked_before_follower_execution(
    tmp_path, monkeypatch
):
    _, client, request = _dilution_case(tmp_path)
    application = client.app.state.application
    preparation_request = ValuationEvidenceReadRequestV1.model_validate(
        request["preparation"]
    )
    original_loader = service_module.load_release_dilution_evidence
    loader_calls = 0

    def reject_follower(*args, **kwargs):
        nonlocal loader_calls
        loader_calls += 1
        if loader_calls == 2:
            raise service_module.DilutionError(
                "DILUTION_QUOTE_ADMISSION_REFUSED", "quote permission was revoked"
            )
        return original_loader(*args, **kwargs)

    monkeypatch.setattr(
        service_module, "load_release_dilution_evidence", reject_follower
    )
    owner = application.prepare_valuation_operation(
        preparation_request, deadline_at=datetime.now(UTC) + timedelta(seconds=30)
    )
    value = owner.preparation.input
    assert value is not None and value.input_digest is not None
    shared = ImmutableAutomaticValuationPreparation.capture(
        owner.preparation, expected_input_digest=value.input_digest
    )
    with pytest.raises(service_module.ServiceError) as error:
        application.reuse_automatic_valuation_operation(
            preparation_request,
            shared,
            expected_input_digest=request["expected_input_digest"],
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        )
    assert error.value.code == "DILUTION_QUOTE_ADMISSION_REFUSED"
    assert loader_calls == 2


def test_follower_quote_replay_deadline_refuses_before_approval_and_execution(
    tmp_path, monkeypatch
):
    _, client, _, request = _case(tmp_path)
    app = client.app
    release_preparation = Event()
    preparation_started = Event()
    follower_joined = Event()
    loader_calls = 0
    publication_calls = 0
    calculator_calls = 0
    original_loader = service_module.load_release_conditional_quote
    original_prepare = FundamentalApplication.prepare_valuation_operation
    original_join = app.state.automatic_valuation_flights.join
    original_publish = AutomaticValuationExecutor._publish
    original_calculate = service_module.calculate

    def slow_follower_loader(*args, **kwargs):
        nonlocal loader_calls
        loader_calls += 1
        if loader_calls == 2:
            sleep(0.3)
        return original_loader(*args, **kwargs)

    def prepare(self, *args, **kwargs):
        operation = original_prepare(self, *args, **kwargs)
        preparation_started.set()
        assert release_preparation.wait(5), "test did not release preparation"
        return operation

    def join(key):
        lease = original_join(key)
        if lease is not None and not lease.is_owner:
            follower_joined.set()
        return lease

    def publish(self, *args, **kwargs):
        nonlocal publication_calls
        publication_calls += 1
        return original_publish(self, *args, **kwargs)

    def calculate(*args, **kwargs):
        nonlocal calculator_calls
        calculator_calls += 1
        if calculator_calls > 1:
            raise AssertionError("deadline-expired follower entered calculation")
        return original_calculate(*args, **kwargs)

    monkeypatch.setattr(
        service_module, "load_release_conditional_quote", slow_follower_loader
    )
    monkeypatch.setattr(FundamentalApplication, "prepare_valuation_operation", prepare)
    monkeypatch.setattr(app.state.automatic_valuation_flights, "join", join)
    monkeypatch.setattr(AutomaticValuationExecutor, "_publish", publish)
    monkeypatch.setattr(service_module, "calculate", calculate)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://service"
        ) as http:
            owner = asyncio.create_task(
                http.post(
                    "/v1/valuation/calculate-automatically",
                    headers=auth_headers(),
                    json=make_internal_envelope(
                        request, correlation_id="deadline-quote-owner"
                    ),
                )
            )
            assert await asyncio.to_thread(preparation_started.wait, 3)
            follower = asyncio.create_task(
                http.post(
                    "/v1/valuation/calculate-automatically",
                    headers=auth_headers(),
                    json=make_internal_envelope(
                        request,
                        correlation_id="deadline-quote-follower",
                        deadline_at=datetime.now(UTC) + timedelta(milliseconds=200),
                    ),
                )
            )
            assert await asyncio.to_thread(follower_joined.wait, 3)
            release_preparation.set()
            return await asyncio.gather(owner, follower)

    owner_response, follower_response = asyncio.run(exercise())
    assert owner_response.status_code == 200, owner_response.text
    assert follower_response.status_code == 408, follower_response.text
    assert follower_response.json()["error"]["code"] == "REQUEST_DEADLINE_EXCEEDED"
    assert "result" not in follower_response.json()
    assert loader_calls == 2
    assert publication_calls == 4
