"""Synthetic policy/caller checks; real issuer acceptance is separate."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fundamental_service.app import create_app
from fundamental_service.application.service import FundamentalApplication
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
from fundamental_service.contracts import ValuationEvidenceReadRequestV1
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


def test_authenticated_policy_decision_executes_and_reuses_exact_evidence(tmp_path):
    fixture, client, policy, request = _case(tmp_path)
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

    monkeypatch.setattr(FundamentalApplication, "calculate_valuation", forbidden)
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

    monkeypatch.setattr(FundamentalApplication, "calculate_valuation", forbidden)
    repeated = _execute(client, request)
    assert repeated.status_code == 422, repeated.text
    assert repeated.json()["error"]["code"] == "ARTIFACT_BYTES_UNAVAILABLE"


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
