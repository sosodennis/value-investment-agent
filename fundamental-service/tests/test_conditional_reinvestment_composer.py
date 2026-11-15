"""Synthetic owning-boundary checks; no real issuer/caller acceptance claim."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from fundamental_service.conditional_reinvestment import (
    bind_conditional_reinvestment_recipe,
)
from fundamental_service.conditional_reinvestment_contracts import REINVESTMENT_UNKNOWNS
from fundamental_service.conditional_reinvestment_release import (
    REINVESTMENT_ASSUMPTION_ROLE,
    reinvestment_assumption_document,
)
from fundamental_service.contracts import SourceSnapshotV1, ValuationInputV1
from fundamental_service.data_releases import ArtifactRefV1
from fundamental_service.facts import FilesystemCanonicalFactRepository
from fundamental_service.serialization import sha256_digest
from fundamental_service.snapshots import FilesystemSnapshotRepository
from fundamental_service.testsupport import auth_headers, make_internal_envelope
from fundamental_service.valuation_preparation import (
    AutomaticValuationPreparationV1,
    CONDITIONAL_REINVESTMENT_COMPOSER_VERSION,
    ManualProvenanceV1,
    PreparationError,
    apply_manual_override,
    prepare_automatic_valuation,
)
from fundamental_service.valuation_requirements import (
    conditional_reinvestment_requirements_profile,
    valuation_requirements_profile,
)
from test_api import _release_manifest_for
from test_conditional_capital_release import _conditional_fixture
from test_conditional_capital_composer import _approved, _calculate
from test_conditional_reinvestment import _recipe
from test_preparation_runner import _reviewed_candidate
from test_valuation_release_inputs import _client, _manifest_with, _prepare


def _fixture(tmp_path):
    fixture = _conditional_fixture(tmp_path)
    payload = fixture.snapshot.model_dump(exclude={"manifest_digest"})
    payload["source_records"] = tuple(
        source.model_copy(update={"form": "10-K"})
        for source in fixture.snapshot.source_records
    )
    snapshot = SourceSnapshotV1(
        **payload,
        manifest_digest=sha256_digest(
            {key: value for key, value in payload.items() if key != "snapshot_id"}
        ),
    )
    exact = valuation_requirements_profile("fcff_dcf")
    profile = conditional_reinvestment_requirements_profile(
        "fcff_dcf", conditional_capital=True
    )
    allowed = {*profile.required_fact_fields, *profile.supporting_fact_fields}
    removed = {
        "capital_expenditure",
        "depreciation_and_amortization",
        *exact.annual_instant_fields,
        "current_assets",
        "current_liabilities",
    }
    facts = tuple(
        fact.model_copy(
            update={
                "context": fact.context.model_copy(update={"unit_qname": "iso4217:USD"})
            }
        )
        if fact.normalized_field
        in {"revenue", "operating_income", "income_before_tax", "income_tax_expense"}
        else fact
        for fact in fixture.stored
        if fact.normalized_field not in removed and fact.normalized_field in allowed
    )
    fixture.snapshot = snapshot
    fixture.snapshots = FilesystemSnapshotRepository(tmp_path / "forward-snapshots")
    fixture.snapshots.publish(snapshot)
    fixture.facts = FilesystemCanonicalFactRepository(tmp_path / "forward-facts")
    for fact in facts:
        fixture.facts.publish(fact)
    fixture.capital_policy = fixture.capital_policy.model_copy(
        update={
            "snapshot_manifest_digest": snapshot.manifest_digest,
        }
    )
    recipe = _recipe().model_copy(
        update={"mapping_version": fixture.capital_policy.mapping_version}
    )
    record = fixture.artifacts.put_bytes_with_receipt(
        "forward-assumptions",
        reinvestment_assumption_document(recipe),
        media_type="application/json",
    ).artifact
    recipe = recipe.model_copy(
        update={
            "assumption_document_uri": f"artifact://{record.artifact_id}",
            "assumption_document_digest": record.content_hash,
        }
    )
    fixture.forward_policy = bind_conditional_reinvestment_recipe(
        recipe, facts, snapshot=snapshot
    ).policy
    profile = conditional_reinvestment_requirements_profile(
        "fcff_dcf", conditional_capital=True
    )
    fixture.manifest = _manifest_with(
        fixture.manifest,
        snapshot_refs=_release_manifest_for(snapshot, facts).snapshot_refs,
        required_fields=profile.required_fact_fields,
        valuation_working_capital_policy=None,
        conditional_capital_policies=(fixture.capital_policy,),
        conditional_reinvestment_policies=(fixture.forward_policy,),
        artifact_refs=(
            *fixture.manifest.artifact_refs,
            ArtifactRefV1(
                artifact_id=record.artifact_id,
                content_hash=record.content_hash,
                media_type=record.media_type,
                role=REINVESTMENT_ASSUMPTION_ROLE,
            ),
        ),
    )
    fixture.stored = facts
    return fixture


def _prepared(tmp_path):
    fixture = _fixture(tmp_path)
    candidate, canary = _reviewed_candidate(fixture)
    canary.validate(candidate.manifest, candidate.verification)
    client = _client(fixture)
    response = _prepare(client, fixture, candidate)
    assert response.status_code == 200, response.text
    prepared = AutomaticValuationPreparationV1.model_validate_json(
        json.dumps(response.json()["result"])
    )
    assert prepared.status == "prepared", prepared.issue_codes
    return fixture, client, candidate, prepared


def test_joint_forward_and_capital_scenarios_use_the_formal_calculator_and_save(
    tmp_path,
):
    fixture, client, candidate, prepared = _prepared(tmp_path)
    assert (
        prepared.input.provenance.preparation_version
        == CONDITIONAL_REINVESTMENT_COMPOSER_VERSION
    )
    assert prepared.quality_status.value == "provisional"
    assert set(REINVESTMENT_UNKNOWNS) <= set(prepared.missing_evidence)
    assert not {"reinvestment_rate", "realized_fcff"} & {
        m.metric_id for m in prepared.historical_metrics.metrics
    }
    operating = prepared.conditional_operating
    assert operating.output_digest in prepared.input.assumptions.trace.source_refs
    assert (
        fixture.forward_policy.recipe.assumption_document_digest
        in prepared.input.assumptions.trace.source_refs
    )
    reinvestment = [
        e
        for e in prepared.assumptions_evidence
        if e.path.startswith("assumptions.forecast.reinvestment_rate[")
    ]
    assert len(reinvestment) == 5
    assert all(e.method == "approved_policy" and not e.editable for e in reinvestment)
    assert _prepare(client, fixture, candidate).json()["result"] == prepared.model_dump(
        mode="json"
    )
    # Synthetic caller envelope exercises the boundary only; it is not real approval.
    assert (
        _calculate(client, prepared.input).json()["error"]["code"]
        == "CALLER_APPROVAL_REQUIRED"
    )
    response = _calculate(client, _approved(prepared.input))
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["base"]["per_share_value"] is not None
    assert len(result["scenario_results"]) == 3
    for actual, op, capital in zip(
        result["scenario_results"],
        operating.scenarios,
        prepared.conditional_capital.scenarios,
        strict=True,
    ):
        assert actual["assumptions"]["forecast"] == op.forecast.model_dump(mode="json")
        assert actual["assumptions"]["capital_bridge"] == capital.bridge.model_dump(
            mode="json"
        )
    ref = next(
        r
        for r in result["artifact_references"]
        if r["artifact_type"] == "uncertainty_evidence"
    )
    url = f"/v1/artifacts/{ref['artifact_id']}/content"
    assert (
        client.request("GET", url, json=make_internal_envelope({})).status_code == 401
    )
    saved = client.request(
        "GET", url, headers=auth_headers(), json=make_internal_envelope({})
    )
    assert saved.status_code == 200
    assert (
        json.loads(saved.content)["request"]["assumptions"]
        == prepared.input.model_dump(mode="json")["assumptions"]
    )
    assert _calculate(client, _approved(prepared.input)).json()["result"] == result


@pytest.mark.parametrize(
    "mutation", ("rate", "remove_scenarios", "base", "trace", "quality", "version")
)
def test_changed_forward_input_is_rejected_even_with_new_synthetic_approval(
    tmp_path, mutation
):
    _, client, _, prepared = _prepared(tmp_path)
    payload = prepared.input.model_dump(
        mode="json", exclude={"input_digest", "caller_approval"}
    )
    if mutation == "rate":
        payload["uncertainty"]["scenarios"][1]["assumptions"][
            "assumptions.forecast.reinvestment_rate[0]"
        ] = "0.1"
    elif mutation == "remove_scenarios":
        payload["uncertainty"] = {"mode": "none"}
    elif mutation == "base":
        payload["assumptions"]["forecast"]["reinvestment_rate"][0] = "0.1"
    elif mutation == "trace":
        payload["assumptions"]["trace"]["source_refs"] = []
    elif mutation == "quality":
        payload["quality"]["status"] = "verified"
    else:
        payload["provenance"]["preparation_version"] = "caller-version"
    value = ValuationInputV1.model_validate_json(json.dumps(payload)).with_digest()
    response = _calculate(client, _approved(value))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "CONDITIONAL_REINVESTMENT_INPUT_MISMATCH"


def test_forward_policy_cannot_be_overridden_outside_its_retained_document(tmp_path):
    _, _, _, prepared = _prepared(tmp_path)
    with pytest.raises(PreparationError) as caught:
        apply_manual_override(
            prepared,
            path="assumptions.forecast.reinvestment_rate[0]",
            value=Decimal("0.1"),
            provenance=ManualProvenanceV1(
                author="synthetic-test",
                modified_at=prepared.input.valuation_context.valuation_timestamp,
                reason="attempt to bypass immutable assumptions",
                automatic_preparation_digest=prepared.preparation_digest,
            ),
        )
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_OVERRIDE_UNSUPPORTED"


def test_original_bound_policy_refuses_wrong_model_before_composition(tmp_path):
    fixture = _fixture(tmp_path)
    result = prepare_automatic_valuation(
        fixture.stored,
        snapshot=fixture.snapshot,
        model_id="fcff_dcf",
        model_version="fcff_dcf-v1",
        policy_id="policy",
        policy_version="v1",
        data_release_manifest_digest=fixture.manifest.manifest_digest,
        mapping_version=fixture.forward_policy.recipe.mapping_version,
        conditional_reinvestment_policy=fixture.forward_policy,
        conditional_capital_policy=fixture.capital_policy,
    )
    assert result.status == "abstained"
    assert "CONDITIONAL_REINVESTMENT_MODEL_MISMATCH" in result.issue_codes


def test_future_policy_context_does_not_silently_fall_back_to_historical_route(
    tmp_path,
):
    fixture = _fixture(tmp_path)
    result = prepare_automatic_valuation(
        fixture.stored,
        snapshot=fixture.snapshot,
        model_id="fcff_dcf",
        model_version="fcff_dcf-v2",
        policy_id="policy",
        policy_version="v1",
        data_release_manifest_digest=fixture.manifest.manifest_digest,
        mapping_version=fixture.forward_policy.recipe.mapping_version,
        conditional_reinvestment_policy=fixture.forward_policy.model_copy(
            update={
                "valuation_timestamp": fixture.snapshot.valuation_timestamp
                + timedelta(days=1),
            }
        ),
        conditional_capital_policy=fixture.capital_policy,
    )
    assert result.status == "abstained"
    assert "CONDITIONAL_REINVESTMENT_SNAPSHOT_MISMATCH" in result.issue_codes


def test_forward_assumptions_cannot_replace_missing_observed_capital(tmp_path):
    fixture = _fixture(tmp_path)
    result = prepare_automatic_valuation(
        tuple(
            fact
            for fact in fixture.stored
            if fact.normalized_field != "noncontrolling_interests"
        ),
        snapshot=fixture.snapshot,
        model_id="fcff_dcf",
        model_version="fcff_dcf-v2",
        policy_id="policy",
        policy_version="v1",
        data_release_manifest_digest=fixture.manifest.manifest_digest,
        mapping_version=fixture.forward_policy.recipe.mapping_version,
        conditional_reinvestment_policy=fixture.forward_policy,
        conditional_capital_policy=fixture.capital_policy,
    )
    assert result.status == "abstained" and result.input is None
    assert "noncontrolling_interests" in result.missing_evidence


def test_absent_forward_policy_still_requires_observed_reinvestment_history(tmp_path):
    fixture = _fixture(tmp_path)
    result = prepare_automatic_valuation(
        fixture.stored,
        snapshot=fixture.snapshot,
        model_id="fcff_dcf",
        model_version="fcff_dcf-v2",
        policy_id="policy",
        policy_version="v1",
        data_release_manifest_digest=fixture.manifest.manifest_digest,
        mapping_version=fixture.forward_policy.recipe.mapping_version,
        conditional_capital_policy=fixture.capital_policy,
    )
    assert result.status == "abstained" and result.input is None
    assert {"capital_expenditure", "depreciation_and_amortization"} <= set(
        result.missing_evidence
    )
