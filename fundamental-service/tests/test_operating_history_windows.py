"""Explicit study windows preserve composer math and authenticated release gates."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from fundamental_service.contracts import QualityStatus
from fundamental_service.data_releases import DataReleaseError
from fundamental_service.issuer_operating_release import IssuerOperatingReleaseService
from fundamental_service.operating_forecast import OperatingForecastV1
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_issuer_operating_release import fixture, inventory
from test_operating_forecast import operating_facts, prepare
from test_valuation_preparation import _fact


@pytest.mark.parametrize("model", ("fcff_dcf", "transition_fcff_dcf"))
@pytest.mark.parametrize("years", (3, 4, 5))
def test_explicit_windows_use_the_shared_composer_on_exact_trailing_periods(
    model, years
):
    filing = _fact("filed_operating_evidence", 2025, "1").model_copy(
        update={"value": "filed evidence"}
    )
    extra = (filing,) if model == "transition_fcff_dcf" else ()
    facts = (*operating_facts(), *extra)
    result = prepare(facts, model_id=model, history_window_years=years)
    truncated = tuple(fact for fact in facts if fact.period_end.year > 2025 - years)
    baseline = prepare(truncated, model_id=model)
    assert result.status == baseline.status == "prepared"
    assert result.forecast == baseline.forecast
    assert result.tax_rate == baseline.tax_rate
    assert result.nodes == baseline.nodes
    assert result.fiscal_years == tuple(range(2026 - years, 2026))
    assert result.history_window_years == years
    assert result.history_window_policy == "complete-trailing-annual-v1"
    assert set(result.selected_fact_ids) == {fact.fact_id for fact in truncated}
    assert set(result.excluded_history_fact_ids) == {
        fact.fact_id for fact in facts if fact not in truncated
    }
    assert all(
        set(metric.fact_ids) <= set(result.selected_fact_ids)
        for metric in result.historical_metrics.metrics
    )
    assert result.quality_status is QualityStatus.PROVISIONAL
    assert result.supported_history_threshold is None
    assert canonical_bytes(result) == canonical_bytes(
        prepare(tuple(reversed(facts)), model_id=model, history_window_years=years)
    )
    assert result.output_digest == sha256_digest(
        result.model_dump(exclude={"output_digest"})
    )


@pytest.mark.parametrize("years", (4, 5))
def test_requested_window_cannot_silently_use_three_available_periods(years):
    facts = tuple(fact for fact in operating_facts() if fact.period_end.year >= 2023)
    assert prepare(facts).status == "prepared"
    result = prepare(facts, history_window_years=years)
    assert result.status == "abstained"
    assert result.forecast is None and result.tax_rate is None and not result.nodes
    assert "OPERATING_HISTORY_WINDOW_UNAVAILABLE" in result.issue_codes
    assert result.missing_evidence
    assert all(int(item.split(":")[0]) < 2023 for item in result.missing_evidence)
    assert result.history_window_years == years
    assert canonical_bytes(result) == canonical_bytes(
        prepare(tuple(reversed(facts)), history_window_years=years)
    )


def test_excluded_history_does_not_change_targets_but_still_binds_input_identity():
    facts = operating_facts()
    baseline = prepare(facts, history_window_years=3)
    changed = tuple(
        fact.model_copy(update={"value": fact.value + Decimal("1")})
        if fact.normalized_field == "revenue" and fact.period_end.year == 2021
        else fact
        for fact in facts
    )
    result = prepare(changed, history_window_years=3)
    assert result.status == "prepared"
    assert result.forecast == baseline.forecast and result.nodes == baseline.nodes
    assert result.input_digest != baseline.input_digest
    assert result.output_digest != baseline.output_digest
    assert result.excluded_history_fact_ids == baseline.excluded_history_fact_ids
    assert prepare(facts, history_window_years=4).forecast != baseline.forecast


@pytest.mark.parametrize("mutation", ("conflict", "unit", "duplicate", "transition"))
def test_explicit_window_preserves_existing_input_gates(mutation):
    facts = operating_facts()
    model = "fcff_dcf"
    expected = "HISTORY_FACT_CONFLICT"
    older = next(fact for fact in facts if fact.period_end.year == 2021)
    if mutation == "conflict":
        facts = (
            *facts,
            older.model_copy(update={"fact_id": "conflict", "value": Decimal("1")}),
        )
    elif mutation == "unit":
        facts = tuple(
            fact.model_copy(update={"unit": "EUR"}) if fact == older else fact
            for fact in facts
        )
        expected = "OPERATING_FACT_UNIT_INVALID"
    elif mutation == "duplicate":
        facts = (*facts, older)
        expected = "OPERATING_FACT_ID_DUPLICATE"
    else:
        model = "transition_fcff_dcf"
        expected = "VALUATION_REQUIRED_FACTS_MISSING"
    result = prepare(facts, model_id=model, history_window_years=3)
    assert result.status == "abstained" and result.forecast is None
    assert expected in result.issue_codes


def test_rejected_observations_and_gaps_cannot_be_hidden_by_an_explicit_window():
    facts = operating_facts()
    latest_revenue = next(
        fact
        for fact in facts
        if fact.normalized_field == "revenue" and fact.period_end.year == 2025
    )
    rejected = latest_revenue.model_copy(
        update={"fact_id": "unreleased-revenue", "quality": QualityStatus.PROVISIONAL}
    )
    result = prepare((*facts, rejected), history_window_years=3)
    assert rejected.fact_id in result.rejected_fact_ids
    assert result.input_digest != prepare(facts, history_window_years=3).input_digest
    gap = prepare(
        tuple(fact for fact in facts if fact.period_end.year != 2024),
        history_window_years=3,
    )
    assert gap.status == "abstained" and gap.forecast is None
    assert "OPERATING_HISTORY_WINDOW_UNAVAILABLE" in gap.issue_codes
    assert any(item.startswith("2024:") for item in gap.missing_evidence)


@pytest.mark.parametrize("years", (0, 1, 2, 6, True, "3", 3.0))
def test_unknown_window_requests_fail_at_the_function_boundary(years):
    with pytest.raises(ValueError, match="three, four or five"):
        prepare(operating_facts(), history_window_years=years)


def test_default_wire_shape_and_explicit_window_coherence():
    baseline = prepare(operating_facts())
    assert (
        not {
            "history_window_years",
            "history_window_policy",
            "excluded_history_fact_ids",
        }
        & baseline.model_dump().keys()
    )
    assert canonical_bytes(baseline) == canonical_bytes(
        prepare(operating_facts(), history_window_years=None)
    )
    explicit = prepare(operating_facts(), history_window_years=3)
    for changes in (
        {"history_window_years": 5},
        {"history_window_policy": None},
        {"excluded_history_fact_ids": explicit.selected_fact_ids[:1]},
    ):
        with pytest.raises(ValidationError):
            OperatingForecastV1.model_validate({**explicit.model_dump(), **changes})


def test_authenticated_release_window_repeat_retains_authority_and_artifact_inventory(
    tmp_path,
):
    bundle, service, evidence, roots, store = fixture(tmp_path)
    service.publish(bundle)
    before = inventory(store.root)
    kwargs = {
        "artifact_id": bundle.artifact_id,
        "expected_manifest_digest": bundle.manifest.manifest_digest,
        "snapshot_id": bundle.sources[0].snapshot_id,
    }
    restarted = IssuerOperatingReleaseService(
        releases=ArtifactStore(store.root), evidence=evidence, trust_roots=roots
    )
    for years in (3, 4, 5):
        result = service.prepare(**kwargs, history_window_years=years)
        repeat = restarted.prepare(**kwargs, history_window_years=years)
        assert canonical_bytes(result) == canonical_bytes(repeat)
        assert result.forecast.status == "prepared"
        assert len(result.forecast.fiscal_years) == years
        assert result.forecast.history_window_years == years
        assert (
            result.canary.candidate_manifest_digest == bundle.manifest.manifest_digest
        )
        assert inventory(store.root) == before
    with pytest.raises(DataReleaseError, match="exact immutable release"):
        service.prepare(
            **{**kwargs, "expected_manifest_digest": "0" * 64}, history_window_years=3
        )
    with pytest.raises(DataReleaseError):
        IssuerOperatingReleaseService(
            releases=store,
            evidence=evidence,
            trust_roots=roots.model_copy(
                update={
                    "verifiers": {
                        "untrusted-verifier": next(iter(roots.verifiers.values()))
                    }
                }
            ),
        ).prepare(**kwargs, history_window_years=3)
