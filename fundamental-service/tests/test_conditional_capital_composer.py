"""Synthetic authenticated execution checks; no real caller or issuer acceptance."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fundamental_service.contracts import ValuationInputV1
from fundamental_service.equity_award_evidence import EQUITY_DILUTION_ARTIFACT_ROLE
from fundamental_service.data_releases import ArtifactRefV1, DataReleaseError
from fundamental_service.quote_admission import (
    QUOTE_ADMISSION_ROLE,
    QUOTE_TERMS_ROLE,
    EQUITY_QUOTE_SOURCE_ROLE,
    QuoteAdmissionV1,
    admit_quote_source,
)
from fundamental_service.quote_sources import default_quote_providers
from fundamental_service.source_evidence import RetainedSourceV1
from fundamental_service.source_admission import SourceUsePolicyV1
from fundamental_service.testsupport import auth_headers, make_internal_envelope
from fundamental_service.uncertainty import UncertaintyEvidenceV1
from fundamental_service.valuation_preparation import (
    AutomaticValuationPreparationV1,
    ManualProvenanceV1,
    PreparationError,
    apply_manual_override,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.policies import PolicyRecordV1
from test_conditional_capital_release import _conditional_fixture
from test_preparation_runner import _reviewed_candidate
from test_valuation_release_inputs import _client, _manifest_with, _prepare
from equity_award_fixtures import award_evidence


def _prepared_case(tmp_path, *, balance_hypotheses=None):
    fixture = _conditional_fixture(tmp_path, balance_hypotheses=balance_hypotheses)
    candidate, canary = _reviewed_candidate(fixture)
    canary.validate(candidate.manifest, candidate.verification)
    client = _client(fixture)
    response = _prepare(client, fixture, candidate)
    assert response.status_code == 200, response.text
    prepared = AutomaticValuationPreparationV1.model_validate_json(
        json.dumps(response.json()["result"])
    )
    assert prepared.status == "prepared"
    return fixture, client, candidate, prepared


def _calculate(client, value):
    return client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(value.model_dump(mode="json")),
    )


def test_conditional_http_preparation_and_approved_scenarios_save_and_replay(tmp_path):
    fixture, client, candidate, prepared = _prepared_case(tmp_path)
    assert prepared.quality_status.value == "provisional"
    assert set(prepared.conditional_capital.policy.unknowns) <= set(
        prepared.missing_evidence
    )
    assert prepared.equity_dilution is None
    assert prepared.conditional_quote is not None
    assert prepared.input.uncertainty.mode == "scenarios"
    assert (
        prepared.conditional_capital.output_digest
        in prepared.input.assumptions.trace.source_refs
    )
    assert (
        prepared.conditional_quote.content_hash
        in prepared.input.assumptions.trace.source_refs
    )
    assert prepared.input.quality.status.value == "provisional"
    assert all(
        not item.editable and item.method == "approved_policy"
        for item in prepared.assumptions_evidence
        if item.path.startswith("assumptions.capital_bridge.")
    )
    repeat = _prepare(client, fixture, candidate)
    assert repeat.json()["result"] == prepared.model_dump(mode="json")
    value = prepared.input
    first = _calculate(client, value)
    assert first.status_code == 200, first.text
    result = first.json()["result"]
    assert result["status"] == "provisional"
    assert result["requested_samples"] == 0
    assert result["input_digest"] == value.input_digest
    assert result["base"]["quality_status"] == "provisional"
    assert result["base"]["per_share_value"] is not None
    assert len(result["scenario_results"]) == 3
    for actual, scenario in zip(
        result["scenario_results"], prepared.conditional_capital.scenarios, strict=True
    ):
        assert actual["assumptions"]["capital_bridge"] == scenario.bridge.model_dump(
            mode="json"
        )
        assert actual["quality_status"] == "provisional"
    reference = next(
        item
        for item in result["artifact_references"]
        if item["artifact_type"] == "uncertainty_evidence"
    )
    url = f"/v1/artifacts/{reference['artifact_id']}/content"
    assert (
        client.request("GET", url, json=make_internal_envelope({})).status_code == 401
    )
    saved = client.request(
        "GET", url, headers=auth_headers(), json=make_internal_envelope({})
    )
    assert saved.status_code == 200, saved.text
    evidence = UncertaintyEvidenceV1.model_validate_json(saved.content)
    assert evidence.report.input_digest == value.input_digest
    second = _calculate(client, value)
    assert second.status_code == 200, second.text
    assert second.json()["result"] == result
    assert (
        client.request(
            "GET", url, headers=auth_headers(), json=make_internal_envelope({})
        ).content
        == saved.content
    )


@pytest.mark.parametrize(
    "mutation", ["scenario", "remove_scenarios", "quality", "trace", "version", "base"]
)
def test_caller_cannot_turn_conditional_release_into_different_authorized_input(
    tmp_path, mutation
):
    _, client, _, prepared = _prepared_case(tmp_path)
    payload = prepared.input.model_dump(mode="json", exclude={"input_digest"})
    if mutation == "scenario":
        payload["uncertainty"]["scenarios"][1]["assumptions"][
            "assumptions.capital_bridge.debt"
        ] = "999"
    elif mutation == "remove_scenarios":
        payload["uncertainty"] = {"mode": "none"}
    elif mutation == "quality":
        payload["quality"]["status"] = "verified"
    elif mutation == "trace":
        payload["assumptions"]["trace"]["source_refs"] = []
    elif mutation == "version":
        payload["provenance"]["preparation_version"] = "caller-claimed-composer"
    else:
        payload["assumptions"]["capital_bridge"]["debt"] = "999"
    value = ValuationInputV1.model_validate_json(json.dumps(payload)).with_digest()
    response = _calculate(client, value)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "CONDITIONAL_CAPITAL_INPUT_MISMATCH"


def test_changed_conditional_operand_is_rejected_after_recomposition(tmp_path):
    _, client, _, prepared = _prepared_case(tmp_path)
    payload = prepared.input.model_dump(mode="json")
    payload["uncertainty"]["scenarios"][1]["assumptions"][
        "assumptions.capital_bridge.preferred_stock"
    ] = "9"
    payload["input_digest"] = None
    response = client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(payload),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONDITIONAL_CAPITAL_INPUT_MISMATCH"


def test_pinned_conditional_input_replays_after_new_effective_policy_is_registered(
    tmp_path,
):
    fixture, client, candidate, prepared = _prepared_case(tmp_path)
    value = prepared.input
    first = _calculate(client, value)
    assert first.status_code == 200, first.text
    registry = client.app.state.application.policy_registry
    old = registry.policy(value.policy_id)
    payload = old.model_dump(exclude={"policy_digest"}) | {
        "policy_id": old.policy_id + "-later-version",
        "policy_version": old.policy_version + "-later-version",
        "effective_at": old.effective_at + timedelta(seconds=1),
    }
    newer = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    registry.add_policy(newer)
    new_preparation = _prepare(client, fixture, candidate)
    assert new_preparation.status_code == 200, new_preparation.text
    assert new_preparation.json()["result"]["input"]["policy_id"] == newer.policy_id
    assert (
        new_preparation.json()["result"]["input"]["input_digest"] != value.input_digest
    )
    repeated = _calculate(client, value)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["result"] == first.json()["result"]


def test_alternate_uncertainty_route_cannot_drop_conditional_scenarios(tmp_path):
    _, client, _, prepared = _prepared_case(tmp_path)
    payload = prepared.input.model_dump(mode="json", exclude={"input_digest"})
    response = client.post(
        "/v1/valuation/uncertainty",
        headers=auth_headers(),
        json=make_internal_envelope(payload),
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "CONDITIONAL_CAPITAL_INPUT_MISMATCH"


@pytest.mark.parametrize(
    "failure", ["missing_admission", "missing_terms", "no_policy", "stale", "inventory"]
)
def test_canary_and_serving_refuse_same_ineligible_conditional_quote(tmp_path, failure):
    fixture = _conditional_fixture(tmp_path)
    expected = {
        "missing_admission": "DILUTION_QUOTE_ADMISSION_MISSING",
        "missing_terms": "DILUTION_QUOTE_TERMS_MISSING",
        "no_policy": "DILUTION_QUOTE_USE_POLICY_UNAVAILABLE",
        "stale": "DILUTION_QUOTE_STALE",
        "inventory": "CONDITIONAL_CAPITAL_INVENTORY_CONFLICT",
    }[failure]
    if failure in {"missing_admission", "missing_terms"}:
        role = (
            QUOTE_ADMISSION_ROLE if failure == "missing_admission" else QUOTE_TERMS_ROLE
        )
        fixture.manifest = _manifest_with(
            fixture.manifest,
            artifact_refs=tuple(
                ref for ref in fixture.manifest.artifact_refs if ref.role != role
            ),
        )
    elif failure == "no_policy":
        fixture.application = replace(
            fixture.application,
            source_use_policy=SourceUsePolicyV1(policy_version="no-permission"),
        )
    elif failure == "stale":
        policy = fixture.capital_policy.model_copy(update={"max_quote_age_seconds": 1})
        fixture.manifest = _manifest_with(
            fixture.manifest, conditional_capital_policies=(policy,)
        )
    else:
        dilution = award_evidence(fixture.snapshot)
        record = fixture.artifacts.put_with_receipt("conflicting-inventory", dilution)
        fixture.manifest = _manifest_with(
            fixture.manifest,
            artifact_refs=(
                *fixture.manifest.artifact_refs,
                ArtifactRefV1(
                    artifact_id=record.artifact.artifact_id,
                    content_hash=record.artifact.content_hash,
                    media_type="application/json",
                    role=EQUITY_DILUTION_ARTIFACT_ROLE,
                ),
            ),
        )
    candidate, canary = _reviewed_candidate(fixture)
    with pytest.raises(DataReleaseError) as error:
        canary.validate(candidate.manifest, candidate.verification)
    if failure == "no_policy":
        expected = "DILUTION_QUOTE_ADMISSION_REPLAY_MISMATCH"
    assert error.value.code == expected
    response = _prepare(_client(fixture), fixture, candidate)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == expected


def test_conditional_manual_override_requires_a_formal_override_policy(tmp_path):
    _, _, _, prepared = _prepared_case(tmp_path)
    before = canonical_bytes(prepared)
    with pytest.raises(PreparationError) as error:
        apply_manual_override(
            prepared,
            path="assumptions.terminal_growth",
            value=prepared.input.assumptions.terminal_growth,
            provenance=ManualProvenanceV1(
                reason="Synthetic override attempt without conditional override authority",
                author="test",
                modified_at=datetime.now(UTC),
                automatic_preparation_digest=prepared.preparation_digest,
            ),
        )
    assert error.value.code == "CONDITIONAL_CAPITAL_OVERRIDE_UNSUPPORTED"
    assert canonical_bytes(prepared) == before


def test_future_quote_retains_refusal_in_canary_and_composer(tmp_path):
    fixture = _conditional_fixture(tmp_path)
    ref = next(
        ref
        for ref in fixture.manifest.artifact_refs
        if ref.role == QUOTE_ADMISSION_ROLE
    )
    old = QuoteAdmissionV1.model_validate_json(fixture.artifacts.read(ref.artifact_id))
    future = fixture.snapshot.valuation_timestamp + timedelta(days=1)
    quote = old.request.quote.model_copy(
        update={"available_at": future, "captured_at": future}
    )
    quote_ref = next(
        ref
        for ref in fixture.manifest.artifact_refs
        if ref.role == EQUITY_QUOTE_SOURCE_ROLE
    )
    terms = tuple(
        RetainedSourceV1(
            source_id=item.source_id,
            uri=item.uri,
            source_version=item.source_version,
            terms_reference=item.terms_reference,
            captured_at=item.captured_at,
            content=fixture.artifacts.read(
                next(
                    ref.artifact_id
                    for ref in fixture.manifest.artifact_refs
                    if ref.role == QUOTE_TERMS_ROLE
                    and ref.content_hash == item.content_sha256
                )
            ),
        )
        for item in old.request.terms_artifacts
    )
    admission = admit_quote_source(
        quote,
        fixture.artifacts.read(quote_ref.artifact_id),
        providers=default_quote_providers(),
        terms=terms,
        policy=fixture.application.source_use_policy,
        valuation_at=fixture.snapshot.valuation_timestamp,
    )
    assert admission.status == "refused"
    assert "SOURCE_NOT_AVAILABLE_AT_VALUATION" in admission.issue_codes
    stored = fixture.artifacts.put_with_receipt("future-quote-refusal", admission)
    replacement = ArtifactRefV1(
        artifact_id=stored.artifact.artifact_id,
        content_hash=stored.artifact.content_hash,
        media_type="application/json",
        role=QUOTE_ADMISSION_ROLE,
    )
    fixture.manifest = _manifest_with(
        fixture.manifest,
        artifact_refs=tuple(
            replacement if item.role == QUOTE_ADMISSION_ROLE else item
            for item in fixture.manifest.artifact_refs
        ),
    )
    candidate, canary = _reviewed_candidate(fixture)
    with pytest.raises(DataReleaseError) as error:
        canary.validate(candidate.manifest, candidate.verification)
    assert error.value.code == "DILUTION_FUTURE_EVIDENCE"
    response = _prepare(_client(fixture), fixture, candidate)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DILUTION_FUTURE_EVIDENCE"


def test_corrupt_quote_bytes_refuse_before_preparation_or_calculation(
    tmp_path, monkeypatch
):
    fixture = _conditional_fixture(tmp_path)
    candidate, canary = _reviewed_candidate(fixture)
    ref = next(
        ref
        for ref in candidate.manifest.artifact_refs
        if ref.role == EQUITY_QUOTE_SOURCE_ROLE
    )
    read = fixture.artifacts.read
    monkeypatch.setattr(
        fixture.artifacts,
        "read",
        lambda identifier: read(identifier) + b"corrupt"
        if identifier == ref.artifact_id
        else read(identifier),
    )
    with pytest.raises(DataReleaseError) as error:
        canary.validate(candidate.manifest, candidate.verification)
    assert error.value.code == "DATA_RELEASE_ARTIFACT_HASH_MISMATCH"
    response = _prepare(_client(fixture), fixture, candidate)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DATA_RELEASE_ARTIFACT_HASH_MISMATCH"
