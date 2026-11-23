"""Retained revision authority and conditional MC at the authenticated service boundary."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest
from src.shared.internal_services import InternalPrincipal, build_internal_context

from fundamental_service import uncertainty
from fundamental_service.contracts import (
    ValuationInputV1,
)
from fundamental_service.serialization import canonical_bytes
from fundamental_service.testsupport import TEST_SERVICE_TOKEN, auth_headers
from fundamental_service.uncertainty_policy import CONDITIONAL_SAMPLED_PATHS
from fundamental_service.valuation_preparation import AutomaticValuationPreparationV1
from test_conditional_reinvestment_composer import _prepared


def _envelope(
    value, *, subject="subject-test", organization="organization-test", deadline=None
):
    context = build_internal_context(
        principal=InternalPrincipal(
            subject_id=subject,
            organization_id=organization,
            membership_id="membership-test",
        ),
        correlation_id="conditional-revision-test",
        deadline_at=deadline or datetime.now(UTC) + timedelta(seconds=30),
        audience="fundamental-service",
        signing_key=TEST_SERVICE_TOKEN,
    )
    return {"context": context.model_dump(mode="json"), "input": value}


def _request(
    prepared,
    *,
    value="0.025",
    reason="User terminal assumption",
    path="assumptions.terminal_growth",
):
    return {
        "preparation": prepared.model_dump(mode="json"),
        "path": path,
        "value": value,
        "provenance": {
            "author": "untrusted-display-author",
            "modified_at": "2026-01-15T00:00:00Z",
            "reason": reason,
            "automatic_preparation_digest": prepared.preparation_digest,
        },
    }


def _override(client, prepared, **changes):
    return client.post(
        "/v1/valuation/prepare/override",
        headers=auth_headers(),
        json=_envelope(_request(prepared, **changes)),
    )


def _revised(tmp_path):
    fixture, client, candidate, automatic = _prepared(tmp_path)
    response = _override(client, automatic)
    assert response.status_code == 200, response.text
    revised = AutomaticValuationPreparationV1.model_validate_json(
        json.dumps(response.json()["result"])
    )
    return fixture, client, automatic, revised


def _calculate(
    client, value, *, subject="subject-test", organization="organization-test"
):
    return client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(organization_id=organization),
        json=_envelope(
            value.model_dump(mode="json"), subject=subject, organization=organization
        ),
    )


def test_conditional_mc_never_samples_hypothesis_owned_paths(tmp_path, monkeypatch):
    _, _, _, prepared = _prepared(tmp_path)
    request = prepared.input
    spec = request.uncertainty
    assert spec.mode == "monte_carlo" and spec.samples == 256
    assert tuple(item.path for item in spec.parameters) == CONDITIONAL_SAMPLED_PATHS
    assert tuple(item.name for item in spec.scenarios) == ("base", "downside", "upside")
    assert spec.quantile_basis.hypothesis_probabilities == "not_assigned"
    observed = []
    original = uncertainty.calculate

    def record(value, **kwargs):
        observed.append(value.assumptions)
        return original(value, **kwargs)

    monkeypatch.setattr(uncertainty, "calculate", record)
    with localcontext() as context:
        context.prec = 8
        first = uncertainty.run_uncertainty(request, allow_provisional=True)
    with localcontext() as context:
        context.prec = 47
        second = uncertainty.run_uncertainty(request, allow_provisional=True)
    assert first == second
    assert first.quantile_basis == spec.quantile_basis
    assert first.requested_samples == 256
    assert first.valid_samples + first.invalid_samples == 256
    assert set(first.quantiles) == {"p05", "p50", "p95", "lower", "median", "upper"}
    assert len(observed) == 2 * 260
    for offset in (0, 260):
        for actual in observed[offset + 4 : offset + 260]:
            assert actual.capital_bridge == request.assumptions.capital_bridge
            assert (
                actual.forecast.reinvestment_rate
                == request.assumptions.forecast.reinvestment_rate
            )


def test_revision_retains_complete_preparation_and_reproduces_authenticated_artifacts(
    tmp_path,
):
    fixture, client, automatic, revised = _revised(tmp_path)
    original_bytes = canonical_bytes(automatic)
    for field in (
        "conditional_capital",
        "conditional_operating",
        "conditional_quote",
        "historical_metrics",
        "equity_dilution",
        "profile_digest",
        "quality_status",
        "missing_evidence",
    ):
        assert getattr(revised, field) == getattr(automatic, field)
    assert revised.input.uncertainty.scenarios == automatic.input.uncertainty.scenarios
    assert revised.input.assumptions.terminal_growth == Decimal("0.025")
    assert revised.input.input_digest != automatic.input.input_digest
    assert revised.preparation_digest != automatic.preparation_digest
    assert not any(item.editable for item in revised.assumptions_evidence)
    assert [item.path for item in automatic.assumptions_evidence if item.editable] == [
        "assumptions.terminal_growth"
    ]
    manual = revised.assumptions_evidence[-1]
    assert (
        manual.method == "manual" and manual.manual_provenance.author == "subject-test"
    )
    assert (
        manual.manual_provenance.automatic_preparation_digest
        == automatic.preparation_digest
    )
    ref = revised.input.provenance.conditional_revision_ref
    assert fixture.artifacts.get(ref.artifact_id).content_hash == ref.content_hash
    assert _override(client, automatic).json()["result"] == revised.model_dump(
        mode="json"
    )
    first = _calculate(client, revised.input)
    assert first.status_code == 200, first.text
    result = first.json()["result"]
    assert (
        result["requested_samples"] == 256
        and result["quantile_basis"]["conditioning"] == "retained_base_joint_hypotheses"
    )
    assert _calculate(client, revised.input).json()["result"] == result
    automatic_result = _calculate(client, automatic.input)
    assert automatic_result.status_code == 200, automatic_result.text
    assert (
        automatic_result.json()["result"]["base"]["per_share_value"]
        != result["base"]["per_share_value"]
    )
    refs = [ref, *result["base"]["artifact_references"], *result["artifact_references"]]
    for item in refs:
        artifact_id = (
            item.artifact_id if hasattr(item, "artifact_id") else item["artifact_id"]
        )
        record = fixture.artifacts.get(artifact_id)
        if artifact_id != ref.artifact_id:
            assert ref.content_hash in record.dependency_hashes
        for suffix in ("", "/content"):
            response = client.request(
                "GET",
                f"/v1/artifacts/{artifact_id}{suffix}",
                headers=auth_headers(),
                json=_envelope({}),
            )
            assert response.status_code == 200, response.text
    assert canonical_bytes(automatic) == original_bytes


def test_seed_depends_on_financial_change_but_not_issued_attribution(tmp_path):
    _, client, _, automatic = _prepared(tmp_path)
    responses = [
        _override(client, automatic, reason=reason)
        for reason in ("First user reason", "Second user reason")
    ]
    assert all(response.status_code == 200 for response in responses)
    first, second = [
        AutomaticValuationPreparationV1.model_validate_json(
            json.dumps(response.json()["result"])
        )
        for response in responses
    ]
    assert (
        first.input.provenance.conditional_revision_ref
        != second.input.provenance.conditional_revision_ref
    )
    assert first.input.input_digest != second.input.input_digest
    assert first.input.uncertainty.seed == second.input.uncertainty.seed
    assert first.input.uncertainty.seed != automatic.input.uncertainty.seed
    other = client.post(
        "/v1/valuation/prepare/override",
        headers=auth_headers(),
        json=_envelope(_request(automatic), subject="another-subject"),
    )
    assert other.status_code == 200, other.text
    assert (
        other.json()["result"]["input"]["uncertainty"]["seed"]
        == first.input.uncertainty.seed
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "terminal",
        "capital",
        "reinvestment",
        "scenario",
        "seed",
        "samples",
        "distribution",
        "basis",
        "policy",
        "quote",
        "facts",
        "proof",
    ),
)
def test_genuine_proof_does_not_authorize_any_second_change(tmp_path, mutation):
    _, client, automatic, revised = _revised(tmp_path)
    payload = revised.input.model_dump(mode="json", exclude={"input_digest"})
    if mutation == "terminal":
        payload["assumptions"]["terminal_growth"] = "0.021"
    elif mutation == "capital":
        payload["assumptions"]["capital_bridge"]["debt"] = "999"
    elif mutation == "reinvestment":
        payload["assumptions"]["forecast"]["reinvestment_rate"][0] = "0.11"
    elif mutation == "scenario":
        payload["uncertainty"]["scenarios"][1]["assumptions"][
            "assumptions.forecast.reinvestment_rate[0]"
        ] = "0.11"
    elif mutation == "seed":
        payload["uncertainty"]["seed"] += 1
    elif mutation == "samples":
        payload["uncertainty"]["samples"] = 128
    elif mutation == "distribution":
        payload["uncertainty"]["parameters"][0]["upper"] = "0.8"
    elif mutation == "basis":
        payload["uncertainty"]["quantile_basis"]["joint_scenarios_digest"] = "f" * 64
    elif mutation == "policy":
        payload["uncertainty"]["policy_version"] = "caller-policy"
    elif mutation == "quote":
        payload["assumptions"]["trace"]["source_refs"] = []
    elif mutation == "facts":
        payload["historical_facts"] = payload["historical_facts"][:-1]
    else:
        payload["provenance"]["conditional_revision_ref"] = {
            "artifact_id": "conditional-revision-v1-" + "f" * 64,
            "content_hash": "f" * 64,
        }
    value = ValuationInputV1.model_validate_json(json.dumps(payload)).with_digest()
    response = _calculate(client, value)
    assert response.status_code == 422, response.text
    assert "result" not in response.json()


@pytest.mark.parametrize("scope", ("subject", "organization"))
def test_wrong_owner_cannot_calculate_or_read_revision_or_derived_evidence(
    tmp_path, scope
):
    _, client, _, revised = _revised(tmp_path)
    result = _calculate(client, revised.input)
    assert result.status_code == 200, result.text
    result = result.json()["result"]
    subject = "another-subject" if scope == "subject" else "subject-test"
    organization = (
        "another-organization" if scope == "organization" else "organization-test"
    )
    response = _calculate(
        client, revised.input, subject=subject, organization=organization
    )
    assert response.status_code == 403, response.text
    artifact_ids = {
        revised.input.provenance.conditional_revision_ref.artifact_id,
        *(item["artifact_id"] for item in result["base"]["artifact_references"]),
        *(item["artifact_id"] for item in result["artifact_references"]),
    }
    for artifact_id in artifact_ids:
        for suffix in ("", "/content"):
            response = client.request(
                "GET",
                f"/v1/artifacts/{artifact_id}{suffix}",
                headers=auth_headers(organization_id=organization),
                json=_envelope({}, subject=subject, organization=organization),
            )
            assert response.status_code == 403, response.text
            assert (
                "content_hash" not in response.text
                and "terminal_growth" not in response.text
            )


@pytest.mark.parametrize(
    "fault",
    ("invalidated", "bytes", "dependencies", "during_read", "retention", "media"),
)
def test_retained_proof_integrity_is_rechecked_at_calculation_and_read(
    tmp_path, monkeypatch, fault
):
    fixture, client, _, revised = _revised(tmp_path)
    ref = revised.input.provenance.conditional_revision_ref
    get = fixture.artifacts.get
    read = fixture.artifacts.read
    if fault == "invalidated":
        fixture.artifacts.invalidate(ref.artifact_id)
    elif fault == "bytes":
        monkeypatch.setattr(
            fixture.artifacts,
            "read",
            lambda artifact_id: read(artifact_id) + b" "
            if artifact_id == ref.artifact_id
            else read(artifact_id),
        )
    elif fault == "during_read":

        def withdraw(artifact_id):
            raw = read(artifact_id)
            if artifact_id == ref.artifact_id:
                fixture.artifacts.invalidate(artifact_id)
            return raw

        monkeypatch.setattr(fixture.artifacts, "read", withdraw)
    else:
        changes = {
            "dependencies": {"dependency_hashes": ()},
            "retention": {"retention": "operational_cache"},
            "media": {"media_type": "text/plain"},
        }[fault]
        monkeypatch.setattr(
            fixture.artifacts,
            "get",
            lambda artifact_id: get(artifact_id).model_copy(update=changes)
            if artifact_id == ref.artifact_id
            else get(artifact_id),
        )
    assert _calculate(client, revised.input).status_code == 422
    for suffix in ("", "/content"):
        response = client.request(
            "GET",
            f"/v1/artifacts/{ref.artifact_id}{suffix}",
            headers=auth_headers(),
            json=_envelope({}),
        )
        assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "fault",
    (
        "below",
        "above",
        "noop",
        "path",
        "digest",
        "changed_preparation",
        "citation",
        "naive",
        "chain",
        "nonfinite",
    ),
)
def test_issuance_refuses_unsupported_or_unbound_edits(tmp_path, fault):
    _, client, _, automatic = _prepared(tmp_path)
    request = _request(automatic)
    if fault == "below":
        request["value"] = "-0.001"
    elif fault == "above":
        request["value"] = "0.041"
    elif fault == "noop":
        request["value"] = str(automatic.input.assumptions.terminal_growth)
    elif fault == "path":
        request["path"] = "assumptions.wacc.beta"
    elif fault == "digest":
        request["provenance"]["automatic_preparation_digest"] = "f" * 64
    elif fault == "changed_preparation":
        request["preparation"]["conditional_quote"]["currency"] = "EUR"
    elif fault == "citation":
        request["provenance"]["forward_reference"] = {
            "claim_id": "claim",
            "source_url": "https://example.test",
            "source_content_hash": "f" * 64,
            "citation": "Unsupported external citation",
            "license_reference": "test",
        }
    elif fault == "naive":
        request["provenance"]["modified_at"] = "2026-01-01T00:00:00"
    elif fault == "nonfinite":
        request["value"] = "NaN"
    else:
        response = _override(client, automatic)
        assert response.status_code == 200, response.text
        revised = AutomaticValuationPreparationV1.model_validate_json(
            json.dumps(response.json()["result"])
        )
        request = _request(revised, value="0.021")
    response = client.post(
        "/v1/valuation/prepare/override",
        headers=auth_headers(),
        json=_envelope(request),
    )
    assert response.status_code == (400 if fault in {"naive", "nonfinite"} else 422), (
        response.text
    )


def test_expired_override_cannot_publish_proof(tmp_path):
    fixture, client, _, automatic = _prepared(tmp_path)
    before = {p.name for p in fixture.artifacts.root.iterdir()}
    response = client.post(
        "/v1/valuation/prepare/override",
        headers=auth_headers(),
        json=_envelope(
            _request(automatic), deadline=datetime.now(UTC) - timedelta(seconds=1)
        ),
    )
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "internal_context_deadline_invalid"
    assert {p.name for p in fixture.artifacts.root.iterdir()} == before


@pytest.mark.parametrize(
    "fault", ("seed", "count", "invalid", "basis", "order", "nonfinite", "alias")
)
def test_independent_scenario_check_binds_mc_metadata_without_certifying_draws(
    tmp_path, fault
):
    from fundamental_service.scenario_verification import verify_conditional_arithmetic
    from test_scenario_verification import _rehash

    _, _, _, prepared = _prepared(tmp_path)
    report = uncertainty.run_uncertainty(prepared.input, allow_provisional=True)
    checked = verify_conditional_arithmetic(prepared.input, report)
    assert checked.status == "pass"
    assert any(
        "sampled numerical quantiles and calibration are not independently verified"
        in item
        for item in checked.limitations
    )
    if fault == "seed":
        report = report.model_copy(update={"seed": report.seed + 1})
    elif fault == "count":
        report = report.model_copy(update={"requested_samples": 255})
    elif fault == "invalid":
        report = report.model_copy(update={"invalid_samples": -1})
    elif fault == "basis":
        report = report.model_copy(
            update={
                "quantile_basis": report.quantile_basis.model_copy(
                    update={"conditioning_assumptions_digest": "f" * 64}
                )
            }
        )
    else:
        quantiles = dict(report.quantiles)
        if fault == "order":
            quantiles["p05"] = quantiles["lower"] = Decimal(10) ** 50
        elif fault == "nonfinite":
            quantiles["p50"] = "NaN"
        else:
            quantiles["lower"] = quantiles["p95"]
        report = report.model_copy(update={"quantiles": quantiles})
    checked = verify_conditional_arithmetic(prepared.input, _rehash(report))
    assert checked.status == "fail"
    assert any(item.startswith("sampling:") for item in checked.findings)


def test_policy_route_checks_owner_and_legacy_routes_refuse_revision(tmp_path):
    from fundamental_service.replay import DependencyManifestV1, build_release_manifest

    _, client, _, revised = _revised(tmp_path)
    value = revised.input.model_dump(mode="json")
    policy = client.post(
        "/v1/valuation/calculate-with-policy",
        headers=auth_headers(),
        json=_envelope(value),
    )
    assert policy.status_code == 200, policy.text
    denied = client.post(
        "/v1/valuation/calculate-with-policy",
        headers=auth_headers(),
        json=_envelope(value, subject="another-subject"),
    )
    assert denied.status_code == 403, denied.text
    legacy = client.post(
        "/v1/valuation/uncertainty",
        headers=auth_headers(),
        json=_envelope(
            {key: item for key, item in value.items() if key != "input_digest"}
        ),
    )
    assert legacy.status_code == 422
    assert legacy.json()["error"]["code"] == "CONDITIONAL_UNCERTAINTY_ROUTE_UNSUPPORTED"
    result = policy.json()["result"]["base"]
    manifest = build_release_manifest(
        release_id="revision-refusal-test",
        service_version="test",
        snapshot_ids=(revised.input.valuation_context.data_snapshot_id,),
        input_hashes=(revised.input.input_digest,),
        artifact_hashes=(result["result_hash"],),
        artifact_ids=(result["artifact_references"][0]["artifact_id"],),
        decision_timestamp=revised.input.valuation_context.valuation_timestamp,
        issuer_id=revised.input.identity.issuer_id,
        security_id=revised.input.identity.security_id,
        canonical_fact_ids=revised.input.historical_facts,
        assumption_ids=("assumptions",),
        calibration_artifact_ids=("synthetic-calibration",),
        numerical_settings={"precision": "50"},
        release_profile_thresholds={"quality": "provisional"},
        dependencies=DependencyManifestV1(
            runtime_version="test",
            parser_version="test",
            taxonomy_version="test",
            model_version=revised.model_version,
            calculation_version="calculator-v2",
            source_content_hashes=tuple(result["trace"]["source_content_hashes"]),
        ),
        quality_policy_version="test",
    )
    replay = client.post(
        "/v1/valuation/replay",
        headers=auth_headers(),
        json=_envelope(
            {
                "manifest": manifest.model_dump(mode="json"),
                "request": value,
                "expected": result,
            }
        ),
    )
    assert replay.status_code == 422, replay.text
    assert replay.json()["error"]["code"] == "CONDITIONAL_REPLAY_UNSUPPORTED"
