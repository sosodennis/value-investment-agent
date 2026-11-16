"""In-process preparation reuse never grants approval or hides changed evidence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fundamental_service.application.service import FundamentalApplication
from fundamental_service.contracts import CallerApprovalEnvelopeV1
from fundamental_service.operations import ServiceError
from fundamental_service.quote_admission import QUOTE_ADMISSION_ROLE
from test_automatic_valuation import _case, _execute
from fundamental_service.contracts import ValuationEvidenceReadRequestV1


def prepared_operation(tmp_path):
    fixture, client, _, request = _case(tmp_path)
    application = client.app.state.application
    operation = application.prepare_valuation_operation(
        ValuationEvidenceReadRequestV1.model_validate(request["preparation"]),
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    value = operation.preparation.input
    assert value is not None
    approval = CallerApprovalEnvelopeV1(
        input_digest=value.input_digest,
        decision="approved",
        caller_id="subject-test",
        decided_at=datetime.now(UTC),
    )
    return fixture, application, operation, approval


def test_automatic_request_composes_once_and_next_request_starts_again(
    tmp_path, monkeypatch
):
    _, client, _, request = _case(tmp_path)
    prepare = FundamentalApplication.prepare_valuation
    calls = []

    def observed(self, request, **kwargs):
        calls.append(request)
        return prepare(self, request, **kwargs)

    monkeypatch.setattr(FundamentalApplication, "prepare_valuation", observed)
    first = _execute(client, request)
    assert first.status_code == 200, first.text
    assert len(calls) == 1
    second = _execute(client, request)
    assert second.status_code == 200, second.text
    assert len(calls) == 2
    first_result, second_result = first.json()["result"], second.json()["result"]
    assert first_result["calculation"] == second_result["calculation"]
    for kind in ("preparation", "decision", "execution"):
        a, b = (
            result[kind + "_publication"] for result in (first_result, second_result)
        )
        assert a["artifact"] == b["artifact"] and not b["wrote"]


def test_prepared_calculation_matches_direct_recomposed_calculation(
    tmp_path, monkeypatch
):
    _, application, operation, approval = prepared_operation(tmp_path)
    value = operation.preparation.input.model_copy(update={"caller_approval": approval})
    direct = application.calculate_valuation(value, correlation_id="same-result")

    def repeated(*args, **kwargs):
        pytest.fail("prepared operation must use its checked composition")

    monkeypatch.setattr(FundamentalApplication, "prepare_valuation", repeated)
    assert operation.calculate(approval, correlation_id="same-result") == direct


@pytest.mark.parametrize(
    "fault",
    ("artifact", "fact", "mapping_missing", "mapping_changed", "mapping_status"),
)
def test_evidence_changed_after_policy_decision_is_refused(
    tmp_path, monkeypatch, fault
):
    fixture, client, _, request = _case(tmp_path)
    manifest = fixture.metadata.get_data_release_manifest(
        request["preparation"]["data_release_manifest_digest"]
    )
    publish = fixture.artifacts.put_with_receipt
    mapping_reader = fixture.metadata.get_mapping
    changed = []

    def observed(artifact_id, *args, **kwargs):
        receipt = publish(artifact_id, *args, **kwargs)
        if artifact_id.startswith("automatic-valuation-approval:"):
            changed.append(artifact_id)
            if fault == "artifact":
                ref = next(
                    item
                    for item in manifest.artifact_refs
                    if item.role == QUOTE_ADMISSION_ROLE
                )
                fixture.artifacts.invalidate(ref.artifact_id)
            elif fault.startswith("mapping_"):
                from fundamental_service.snapshots import SnapshotError

                target = manifest.mapping_refs[0].mapping_id

                def changed_mapping(mapping_id):
                    if mapping_id != target:
                        return mapping_reader(mapping_id)
                    if fault == "mapping_missing":
                        raise SnapshotError("MAPPING_NOT_FOUND", "removed mapping")
                    return mapping_reader(mapping_id).model_copy(
                        update={"status": "rejected"}
                        if fault == "mapping_status"
                        else {"mapping_version": "changed-version"}
                    )

                monkeypatch.setattr(fixture.metadata, "get_mapping", changed_mapping)
            else:
                fact_id = manifest.snapshot_refs[0].facts[0].fact_id
                fact = fixture.facts.get(fact_id)
                (fixture.facts.root / (fact_id + ".json")).write_text(
                    fact.model_copy(update={"value": fact.value + 1}).model_dump_json()
                )
        return receipt

    monkeypatch.setattr(fixture.artifacts, "put_with_receipt", observed)
    response = _execute(client, request)
    assert len(changed) == 1
    assert response.status_code == (
        503 if fault == "mapping_missing" else 422 if fault == "artifact" else 409
    ), response.text
    assert (
        response.json()["error"]["code"]
        == {
            "artifact": "ARTIFACT_EVIDENCE_INVALID",
            "fact": "DATA_RELEASE_FACT_MISMATCH",
            "mapping_missing": "MAPPING_NOT_FOUND",
            "mapping_changed": "DATA_RELEASE_MAPPING_MISMATCH",
            "mapping_status": "DATA_RELEASE_MAPPING_MISMATCH",
        }[fault]
    )


@pytest.mark.parametrize("fault", ("changed", "expired", "rejected", "wrong_digest"))
def test_prepared_operation_preserves_exact_input_approval_and_deadline(
    tmp_path, fault
):
    _, _, operation, approval = prepared_operation(tmp_path)
    if fault == "changed":
        operation = replace(
            operation,
            preparation=operation.preparation.model_copy(
                update={
                    "input": operation.preparation.input.model_copy(
                        update={"policy_id": "changed-policy"}
                    )
                }
            ),
        )
    elif fault == "expired":
        operation = replace(
            operation, _deadline_at=datetime.now(UTC) - timedelta(seconds=1)
        )
    elif fault == "rejected":
        approval = approval.model_copy(update={"decision": "rejected"})
    else:
        approval = approval.model_copy(update={"input_digest": "f" * 64})
    with pytest.raises((ServiceError, ValueError)) as caught:
        operation.calculate(approval, correlation_id="refuse-changed")
    if fault == "wrong_digest":
        assert isinstance(caught.value, ServiceError)
        assert caught.value.code == "CALLER_APPROVAL_CONFLICT"
    else:
        assert isinstance(caught.value, ServiceError)
        assert (
            caught.value.code
            == {
                "changed": "PREPARED_VALUATION_CHANGED",
                "expired": "REQUEST_DEADLINE_EXCEEDED",
                "rejected": "CALLER_APPROVAL_REJECTED",
            }[fault]
        )
