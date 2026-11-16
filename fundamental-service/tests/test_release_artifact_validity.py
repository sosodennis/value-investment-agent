"""Retained bytes do not authorize the use of withdrawn release evidence."""

import json
from types import SimpleNamespace

import pytest

from fundamental_service.contracts import ValuationEvidenceReadRequestV1
from fundamental_service.data_releases import DataReleaseError
from fundamental_service.operations import ServiceError
from fundamental_service.artifact_evidence import read_retained_artifact
from fundamental_service.quote_admission import (
    EQUITY_QUOTE_SOURCE_ROLE,
    QUOTE_ADMISSION_ROLE,
    QUOTE_TERMS_ROLE,
)
from test_automatic_valuation import _case, _execute
from test_market_policy_deployment import _deployment_fixture, _canary


@pytest.mark.parametrize(
    "changes",
    (
        {"status": "stale"},
        {"status": "invalidated"},
        {"retention": "operational_cache"},
        {"artifact_id": "substituted"},
        {"content_hash": "0" * 64},
        {"media_type": "text/plain"},
    ),
)
def test_release_evidence_requires_exact_current_metadata(tmp_path, changes):
    fixture, _, _, request = _case(tmp_path)
    manifest = fixture.metadata.get_data_release_manifest(
        request["preparation"]["data_release_manifest_digest"]
    )
    ref = next(
        item for item in manifest.artifact_refs if item.role == QUOTE_ADMISSION_ROLE
    )
    record = fixture.artifacts.get(ref.artifact_id).model_copy(update=changes)
    reader = SimpleNamespace(get=lambda _: record, read=fixture.artifacts.read)
    with pytest.raises(DataReleaseError) as error:
        read_retained_artifact(reader, ref)
    assert error.value.code == "ARTIFACT_EVIDENCE_INVALID"


def test_release_evidence_rejects_invalidation_during_read(tmp_path):
    fixture, _, _, request = _case(tmp_path)
    manifest = fixture.metadata.get_data_release_manifest(
        request["preparation"]["data_release_manifest_digest"]
    )
    ref = next(
        item for item in manifest.artifact_refs if item.role == QUOTE_ADMISSION_ROLE
    )

    def withdraw(artifact_id):
        raw = fixture.artifacts.read(artifact_id)
        fixture.artifacts.invalidate(artifact_id)
        return raw

    reader = SimpleNamespace(get=fixture.artifacts.get, read=withdraw)
    with pytest.raises(DataReleaseError) as error:
        read_retained_artifact(reader, ref)
    assert error.value.code == "ARTIFACT_EVIDENCE_CHANGED"


@pytest.mark.parametrize(
    "role", (EQUITY_QUOTE_SOURCE_ROLE, QUOTE_ADMISSION_ROLE, QUOTE_TERMS_ROLE)
)
def test_automatic_calculation_rejects_withdrawn_quote_bytes(tmp_path, role):
    fixture, client, _, request = _case(tmp_path)
    manifest = fixture.metadata.get_data_release_manifest(
        request["preparation"]["data_release_manifest_digest"]
    )
    ref = next(item for item in manifest.artifact_refs if item.role == role)
    retained = fixture.artifacts.read(ref.artifact_id)
    fixture.artifacts.invalidate(ref.artifact_id)
    assert fixture.artifacts.read(ref.artifact_id) == retained
    response = _execute(client, request)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "ARTIFACT_EVIDENCE_INVALID"
    assert not any(
        json.loads(path.read_bytes()).get("protocol")
        == "automatic-valuation-execution-v1"
        for path in fixture.artifacts.root.glob("*.json.artifact")
    )


@pytest.mark.parametrize(
    "role",
    (
        "market_source_admission",
        "market_source_original",
        "market_source_terms",
        "issuer_market_reference_plan",
        "issuer_terminal_growth_plan",
        "automatic_market_policy_decision",
    ),
)
def test_serving_and_canary_reject_withdrawn_market_evidence(tmp_path, role):
    case = _deployment_fixture(tmp_path)
    fixture = case.fixture
    request = ValuationEvidenceReadRequestV1(
        contract_version="fundamental.v1",
        snapshot_id=fixture.snapshot.snapshot_id,
        data_release_manifest_digest=case.candidate.manifest.manifest_digest,
        model_id="fcff_dcf",
    )
    # Install the checked policy before withdrawing a release dependency.
    from test_market_policy_deployment import _publish

    _publish(case)
    assert fixture.application.prepare_valuation(request).status == "prepared"
    ref = next(
        item for item in case.candidate.manifest.artifact_refs if item.role == role
    )
    retained = fixture.artifacts.read(ref.artifact_id)
    fixture.artifacts.invalidate(ref.artifact_id)
    assert fixture.artifacts.read(ref.artifact_id) == retained
    with pytest.raises(ServiceError) as serving:
        fixture.application.prepare_valuation(request)
    assert serving.value.code == "ARTIFACT_EVIDENCE_INVALID"
    with pytest.raises(DataReleaseError):
        _canary(case).validate(case.candidate.manifest, case.candidate.verification)
