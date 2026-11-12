"""Signed security releases carry the same estimated inputs to canary and composer."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fundamental_service.app import create_app
from fundamental_service.calculator import calculate
from fundamental_service.contracts import UncertaintyV1, ValuationEvidenceReadRequestV1
from fundamental_service.data_releases import (
    ArtifactRefV1,
    DataReleaseError,
    DataReleaseManifestV1,
    MappingRefV1,
)
from fundamental_service.equity_award_evidence import (
    EQUITY_DILUTION_ARTIFACT_ROLE,
    EQUITY_QUOTE_SOURCE_ROLE,
)
from fundamental_service.facts import (
    CanonicalMappingV1,
    FilesystemCanonicalFactRepository,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemSnapshotRepository
from fundamental_service.testsupport import auth_headers, make_internal_envelope
from fundamental_service.valuation_release_inputs import valuation_release_requirements
from fundamental_service.valuation_requirements import (
    composite_working_capital_requirements_profile,
)
from fundamental_service.working_capital import (
    WORKING_CAPITAL_FIELDS,
    ValuationWorkingCapitalPolicyV1,
    canonical_working_capital_inputs,
)
from equity_award_fixtures import award_evidence, quote_source_payload
from test_api import _release_manifest_for
from test_preparation_runner import _fixture, _reviewed_candidate
from test_valuation_preparation import _facts
from test_working_capital import MAPPING_VERSION, _composite_history, _fact_for


def _valuation_fixture(tmp_path: Path):
    fixture = _fixture(tmp_path)
    snapshot, operating, inputs = _composite_history()
    by_id = {fact.fact_id: fact for fact in operating}
    for fact in _facts():
        if fact.normalized_field in WORKING_CAPITAL_FIELDS or fact.fact_id in by_id:
            continue
        by_id[fact.fact_id] = _fact_for(
            fact.normalized_field,
            str(fact.value),
            year=fact.period_end.year,
            instant=fact.instant is not None,
        )
    dilution = award_evidence(snapshot)
    facts = (*by_id.values(), *dilution.facts)
    fixture.snapshot = snapshot
    fixture.snapshots = FilesystemSnapshotRepository(tmp_path / "composite-snapshots")
    fixture.snapshots.publish(snapshot)
    fixture.facts = FilesystemCanonicalFactRepository(tmp_path / "composite-facts")
    fixture.mappings.clear()
    for fact in facts:
        fixture.facts.publish(fact)
        fixture.mappings[fact.mapping_decision_id] = CanonicalMappingV1(
            contract_version="fundamental.v1",
            decision_id=fact.mapping_decision_id,
            source_concept=fact.concept,
            normalized_field=fact.normalized_field,
            mapping_version=MAPPING_VERSION,
            confidence=fact.mapping_confidence,
            status="approved",
            reviewer="contract-test-reviewer",
        )
    fixture.artifacts = ArtifactStore(tmp_path / "composite-artifacts")
    award_id = f"equity-dilution:{dilution.digest}"
    fixture.artifacts.put_with_receipt(award_id, dilution)
    quote = fixture.artifacts.put_with_receipt(
        "synthetic-quote", quote_source_payload(snapshot)
    )
    profile = composite_working_capital_requirements_profile(
        "fcff_dcf", operating_only=False
    )
    policy = ValuationWorkingCapitalPolicyV1(
        model_id="fcff_dcf",
        model_version="fcff_dcf-v2",
        requirements_profile_digest=profile.digest,
        mapping_version=MAPPING_VERSION,
        inputs=canonical_working_capital_inputs(inputs),
    )
    manifest = _release_manifest_for(snapshot, facts)
    fixture.manifest = _manifest_with(
        manifest,
        required_fields=profile.required_fact_fields,
        mapping_refs=tuple(
            MappingRefV1(mapping_id=key, mapping_digest=sha256_digest(mapping))
            for key, mapping in sorted(fixture.mappings.items())
        ),
        artifact_refs=(
            *manifest.artifact_refs,
            ArtifactRefV1(
                artifact_id=award_id,
                content_hash=dilution.digest,
                media_type="application/json",
                role=EQUITY_DILUTION_ARTIFACT_ROLE,
            ),
            ArtifactRefV1(
                artifact_id=quote.artifact.artifact_id,
                content_hash=quote.artifact.content_hash,
                media_type="application/json",
                role=EQUITY_QUOTE_SOURCE_ROLE,
            ),
        ),
        valuation_working_capital_policy=policy,
    )
    fixture.inputs = policy.inputs
    fixture.stored = facts
    return fixture


def _manifest_with(manifest, **changes):
    payload = manifest.model_dump(exclude={"manifest_digest"}) | changes
    return DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))


def _client(fixture):
    return TestClient(
        create_app(
            snapshot_repository=fixture.snapshots,
            fact_repository=fixture.facts,
            artifact_store=fixture.artifacts,
            metadata_store=fixture.metadata,
            config=fixture.application.config,
            policy_registry=fixture.application.policy_registry,
        )
    )


def _prepare(client, fixture, candidate, *, model_id="fcff_dcf"):
    return client.post(
        "/v1/valuation/prepare",
        headers=auth_headers(),
        json=make_internal_envelope(
            {
                "contract_version": "fundamental.v1",
                "snapshot_id": fixture.snapshot.snapshot_id,
                "data_release_manifest_digest": candidate.manifest.manifest_digest,
                "model_id": model_id,
            }
        ),
    )


def test_signed_composite_release_reaches_public_composer_and_calculator(tmp_path):
    fixture = _valuation_fixture(tmp_path)
    candidate, canary = _reviewed_candidate(fixture)
    report = canary.validate(candidate.manifest, candidate.verification)
    assert report == canary.validate(candidate.manifest, candidate.verification)
    client = _client(fixture)
    response = _prepare(client, fixture, candidate)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["status"] == "prepared"
    assert result["quality_status"] == "provisional"
    assert "WORKING_CAPITAL_INPUT_ESTIMATED" in result["issue_codes"]
    assert "HISTORY_THRESHOLD_UNVALIDATED" in result["issue_codes"]
    assert result["input"]["assumptions"]["forecast"] is not None
    assert all(
        assessment["status"] == "estimated"
        and assessment["sensitivity"]
        and assessment["source_facts"]
        and assessment["sensitivity_interpretation"]
        == "deterministic_scenarios_not_confidence_intervals"
        for assessment in result["historical_metrics"]["working_capital_assessments"]
    )
    assert result == _prepare(client, fixture, candidate).json()["result"]
    prepared = client.app.state.application.prepare_valuation(
        ValuationEvidenceReadRequestV1(
            contract_version="fundamental.v1",
            snapshot_id=fixture.snapshot.snapshot_id,
            data_release_manifest_digest=candidate.manifest.manifest_digest,
            model_id="fcff_dcf",
        )
    )
    assert prepared.historical_metrics.working_capital_inputs == fixture.inputs
    assert prepared.input is not None
    calculated = calculate(
        prepared.input.model_copy(
            update={"uncertainty": UncertaintyV1(mode="none")}
        ).with_digest(),
        allow_provisional=True,
    )
    assert calculated.per_share_value > 0


@pytest.mark.parametrize(
    "change",
    [
        {"model_version": "fcff_dcf-v999"},
        {"requirements_profile_digest": "0" * 64},
    ],
)
def test_signed_policy_pin_mismatch_refuses_in_canary_and_http(tmp_path, change):
    fixture = _valuation_fixture(tmp_path)
    policy = fixture.manifest.valuation_working_capital_policy
    fixture.manifest = _manifest_with(
        fixture.manifest,
        valuation_working_capital_policy=policy.model_copy(update=change),
    )
    candidate, canary = _reviewed_candidate(fixture)
    with pytest.raises(DataReleaseError) as caught:
        canary.validate(candidate.manifest, candidate.verification)
    assert caught.value.code == "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH"
    response = _prepare(_client(fixture), fixture, candidate)
    assert response.status_code == 422, response.text
    assert "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH" in response.text


def test_signed_release_cannot_change_the_composite_field_profile(tmp_path):
    fixture = _valuation_fixture(tmp_path)
    fixture.manifest = _manifest_with(
        fixture.manifest,
        required_fields=(*fixture.manifest.required_fields, "contract_assets"),
    )
    candidate, canary = _reviewed_candidate(fixture)
    with pytest.raises(DataReleaseError) as caught:
        canary.validate(candidate.manifest, candidate.verification)
    assert caught.value.code == "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH"
    response = _prepare(_client(fixture), fixture, candidate)
    assert response.status_code == 422, response.text
    assert "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH" in response.text


def test_composite_release_cannot_serve_a_different_model(tmp_path):
    fixture = _valuation_fixture(tmp_path)
    candidate, _ = _reviewed_candidate(fixture)
    response = _prepare(
        _client(fixture), fixture, candidate, model_id="transition_fcff_dcf"
    )
    assert response.status_code == 422, response.text
    assert "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH" in response.text


def test_release_policy_requires_the_same_reviewed_mapping_in_both_boundaries(tmp_path):
    fixture = _valuation_fixture(tmp_path)
    policy = fixture.manifest.valuation_working_capital_policy
    fixture.manifest = _manifest_with(
        fixture.manifest,
        valuation_working_capital_policy=ValuationWorkingCapitalPolicyV1(
            **(
                policy.model_dump()
                | {
                    "mapping_version": "different-mapping",
                    "inputs": tuple(
                        item.model_copy(update={"mapping_version": "different-mapping"})
                        for item in policy.inputs
                    ),
                }
            )
        ),
    )
    candidate, canary = _reviewed_candidate(fixture)
    with pytest.raises(DataReleaseError) as caught:
        canary.validate(candidate.manifest, candidate.verification)
    assert caught.value.code == "DATA_RELEASE_MAPPING_VERSION_MISMATCH"
    response = _prepare(_client(fixture), fixture, candidate)
    assert response.status_code == 422, response.text
    assert "DATA_RELEASE_MAPPING_VERSION_MISMATCH" in response.text


@pytest.mark.parametrize("change", ["source", "unknown", "unbound"])
def test_signed_but_invalid_composite_evidence_is_retained_and_refused(
    tmp_path, change
):
    fixture = _valuation_fixture(tmp_path)
    policy = fixture.manifest.valuation_working_capital_policy
    inputs = []
    for item in policy.inputs:
        payload = item.model_dump()
        if change == "source":
            payload["source_hash"] = "0" * 64
        elif change == "unbound":
            payload["issuer_id"] = "foreign-issuer"
        else:
            payload["exclusions"] = tuple(
                exclusion.model_copy(update={"state": "unknown", "fact_id": None})
                for exclusion in item.exclusions
            )
        inputs.append(type(item).model_validate(payload))
    fixture.manifest = _manifest_with(
        fixture.manifest,
        valuation_working_capital_policy=policy.model_copy(
            update={"inputs": canonical_working_capital_inputs(tuple(inputs))}
        ),
    )
    candidate, canary = _reviewed_candidate(fixture)
    before = canonical_bytes(candidate)
    with pytest.raises(DataReleaseError) as caught:
        canary.validate(candidate.manifest, candidate.verification)
    assert caught.value.code == (
        "DATA_RELEASE_WORKING_CAPITAL_UNBOUND"
        if change == "unbound"
        else "DATA_RELEASE_WORKING_CAPITAL_INVALID"
    )
    response = _prepare(_client(fixture), fixture, candidate)
    if change == "unbound":
        assert response.status_code == 422, response.text
        assert "DATA_RELEASE_WORKING_CAPITAL_UNBOUND" in response.text
    else:
        assert response.status_code == 200, response.text
        assert response.json()["result"]["status"] == "abstained"
        assert response.json()["result"]["input"] is None
    assert canonical_bytes(candidate) == before


def test_signed_release_must_include_each_exclusion_fact(tmp_path):
    fixture = _valuation_fixture(tmp_path)
    reference = fixture.manifest.snapshot_refs[0]
    facts = tuple(
        item
        for item in reference.facts
        if item.fact_id != "cash_and_short_term_investments-2021"
    )
    assert len(facts) == len(reference.facts) - 1
    fixture.manifest = _manifest_with(
        fixture.manifest,
        snapshot_refs=(
            type(reference)(
                **(
                    reference.model_dump()
                    | {"facts": facts, "fact_set_digest": sha256_digest(facts)}
                )
            ),
        ),
    )
    candidate, canary = _reviewed_candidate(fixture)
    with pytest.raises(DataReleaseError) as caught:
        canary.validate(candidate.manifest, candidate.verification)
    assert caught.value.code == "DATA_RELEASE_WORKING_CAPITAL_UNBOUND"
    response = _prepare(_client(fixture), fixture, candidate)
    assert response.status_code == 422, response.text
    assert "DATA_RELEASE_WORKING_CAPITAL_UNBOUND" in response.text


def test_extra_unbound_input_cannot_hide_behind_valid_snapshot_inputs(tmp_path):
    fixture = _valuation_fixture(tmp_path)
    policy = fixture.manifest.valuation_working_capital_policy
    extra = policy.inputs[0].model_copy(update={"issuer_id": "foreign-issuer"})
    fixture.manifest = _manifest_with(
        fixture.manifest,
        valuation_working_capital_policy=policy.model_copy(
            update={"inputs": canonical_working_capital_inputs((*policy.inputs, extra))}
        ),
    )
    candidate, canary = _reviewed_candidate(fixture)
    with pytest.raises(DataReleaseError) as caught:
        canary.validate(candidate.manifest, candidate.verification)
    assert caught.value.code == "DATA_RELEASE_WORKING_CAPITAL_UNBOUND"


def test_absent_policy_preserves_existing_release_bytes_and_digest(tmp_path):
    manifest = _fixture(tmp_path).manifest
    legacy_payload = manifest.model_dump(exclude={"manifest_digest"})
    assert "valuation_working_capital_policy" not in legacy_payload
    assert sha256_digest(legacy_payload) == manifest.manifest_digest
    legacy = canonical_bytes(
        legacy_payload | {"manifest_digest": manifest.manifest_digest}
    )
    assert canonical_bytes(manifest) == legacy
    assert canonical_bytes(DataReleaseManifestV1.model_validate_json(legacy)) == legacy


def test_copied_policy_cannot_bypass_canonical_input_validation(tmp_path):
    fixture = _valuation_fixture(tmp_path)
    policy = fixture.manifest.valuation_working_capital_policy
    copied = policy.model_copy(update={"inputs": tuple(reversed(policy.inputs))})
    manifest = fixture.manifest.model_copy(
        update={"valuation_working_capital_policy": copied}
    )
    with pytest.raises(DataReleaseError) as caught:
        valuation_release_requirements(manifest, "fcff_dcf")
    assert caught.value.code == "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH"
    with pytest.raises(ValidationError, match="periods must be unique"):
        ValuationWorkingCapitalPolicyV1(
            **(policy.model_dump() | {"inputs": (policy.inputs[0],) * 2})
        )
