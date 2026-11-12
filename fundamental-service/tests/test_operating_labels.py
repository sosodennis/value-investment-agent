"""Future originals are outcomes, never forecast inputs or exact ground truth."""

from datetime import UTC, date, datetime
from decimal import Context, Decimal, ROUND_DOWN, localcontext

import pytest
from pydantic import ValidationError

from fundamental_service.contracts import QualityStatus
from fundamental_service.numerical_policy import using_valuation_context
from fundamental_service.operating_comparison_runner import publish_operating_comparison
from fundamental_service.operating_label_contracts import (
    ConditionalLabelRequestV1,
    OperatingComparisonRequestV1,
    OriginalAnnualTargetV1,
    operating_label_policy_digest,
)
from fundamental_service.operating_labels import replay_operating_comparison
from fundamental_service.operating_scenario_contracts import (
    OperatingScenarioV1,
    ScenarioPeriodV1,
)
from fundamental_service.operating_scenarios import replay_operating_scenarios
from fundamental_service.original_issuer import (
    compose_issuer_operating_source,
    evaluate_original_issuer,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_operating_scenarios import request as decision_request


def comparison_request(*, target_assets="240"):
    decision = decision_request()
    previous = decision.source.originals[0]
    available = datetime(2027, 2, 1, tzinfo=UTC)
    accession = "0000000001-27-000001"
    source = previous.source.model_copy(
        update={
            "accession_number": accession,
            "uri": f"https://www.sec.gov/Archives/edgar/data/1/{accession.replace('-', '')}/label.xml",
            "available_at": available,
            "captured_at": datetime(2027, 3, 1, tzinfo=UTC),
            "content_hash": "c" * 64,
            "parser_input_hash": "d" * 64,
        }
    )
    raw = []
    for fact in previous.report.facts:
        updates = {}
        for field in ("period_start", "period_end", "instant"):
            value = getattr(fact, field)
            if value is not None:
                updates[field] = value.replace(year=value.year + 1)
        if fact.concept == "dei:DocumentPeriodEndDate":
            updates["value"] = "2026-12-31"
        if fact.concept == "us-gaap:AssetsCurrent" and fact.instant.year == 2025:
            updates["value"] = target_assets
        raw.append(fact.model_copy(update=updates))
    report = previous.report.model_copy(
        update={"facts": tuple(raw), "source_content_hash": "d" * 64}
    )
    original = evaluate_original_issuer(report, source=source, decision_at=available)
    snapshot = compose_issuer_operating_source(
        (original,), valuation_timestamp=available
    )
    facts = tuple(
        sorted(
            (
                candidate.canonical_fact(quality=QualityStatus.PROVISIONAL)
                for mapping in decision.mappings
                for candidate in parsed_facts_to_candidates(
                    report,
                    source=source,
                    issuer_id=source.cik,
                    normalized_field=mapping.normalized_field,
                    mapping=mapping,
                )
            ),
            key=lambda fact: fact.fact_id,
        )
    )
    periods = tuple(
        ScenarioPeriodV1(
            fiscal_year=year,
            period_start=date(year, 1, 1),
            period_end=date(year, 12, 31),
            fact_ids={
                fact.normalized_field: fact.fact_id
                for fact in facts
                if fact.period_end.year == year
            },
        )
        for year in (2025, 2026)
    )
    scenarios = tuple(
        OperatingScenarioV1(
            scenario_id=f"label-c{fraction}",
            operating_asset_fraction=Decimal(1),
            operating_liability_fraction=Decimal(1),
            continuing_capex_fractions={2025: Decimal(1), 2026: Decimal(fraction)},
            rationale="Explicit conditional capex assumption, not a reported continuing classification.",
        )
        for fraction in (0, 1)
    )
    label = ConditionalLabelRequestV1(
        source=snapshot,
        facts=facts,
        mapping_version=decision.mapping_version,
        mappings=decision.mappings,
        mapping_manifest_digest=decision.mapping_manifest_digest,
        periods=periods,
        scenarios=scenarios,
        scope_assumption_evidence_digests=("f" * 64,),
        unresolved_classes=decision.unresolved_classes,
    )
    inventory = (
        OriginalAnnualTargetV1(
            issuer_id=source.cik,
            accession_number=accession,
            available_at=available,
            period_end=date(2026, 12, 31),
            form="10-K",
            is_amendment=False,
        ),
    )
    return OperatingComparisonRequestV1(
        decision=decision,
        decision_input_digest=sha256_digest(decision),
        label=label,
        filing_inventory=inventory,
        filing_inventory_digest=sha256_digest(inventory),
        inventory_evidence_digest="a" * 64,
        protocol_version="fixed-conditional-fixture-v1",
        policy_digest=operating_label_policy_digest(),
    )


@using_valuation_context
def test_same_filing_shared_metrics_and_prespecified_errors_preserve_transition_refusal():
    request = comparison_request()
    before = canonical_bytes(request)
    result = replay_operating_comparison(request)
    assert canonical_bytes(request) == before
    assert [label.realized_fcff for label in result.labels] == [
        Decimal(45),
        Decimal(25),
    ]
    assert all(
        label.status == "provisional_conditional_label" for label in result.labels
    )
    assert len(result.comparisons) == 4
    for label in result.labels:
        assert label.historical_metrics is not None
        metric = next(
            metric
            for metric in label.historical_metrics.metrics
            if metric.metric_id == "realized_fcff"
        )
        assert metric.value == label.realized_fcff
        assert set(metric.fact_ids) <= set(result.retained_label_fact_ids)
    for row in result.comparisons:
        if row.model_id == "fcff_dcf":
            assert row.status == "provisional_conditional_comparison"
            assert row.signed_error == row.forecast_fcff - row.conditional_realized_fcff
            assert (
                row.normalized_signed_error
                == row.signed_error / row.origin_base_revenue
            )
            assert row.absolute_error == abs(row.signed_error)
        else:
            assert row.status == "abstained" and row.signed_error is None
            assert "TRANSITION_EVIDENCE_MISSING" in row.issue_codes
    assert (
        result.independent_issuer_count == 1 and result.complete_exact_study_cases == 0
    )
    assert result.supported_history_threshold is None
    assert all(
        fact.quality is QualityStatus.PROVISIONAL for fact in request.label.facts
    )


@pytest.mark.parametrize("assets,expected", [("265", "0"), ("400", "-135")])
def test_zero_and_negative_conditional_fcff_are_retained_without_percentage_denominator(
    assets, expected
):
    result = replay_operating_comparison(comparison_request(target_assets=assets))
    assert result.labels[1].realized_fcff == Decimal(expected)
    assert all(
        row.normalized_signed_error is not None
        for row in result.comparisons
        if row.model_id == "fcff_dcf"
    )


def test_changed_future_outcomes_never_change_frozen_forecast():
    before = replay_operating_comparison(comparison_request())
    after = replay_operating_comparison(comparison_request(target_assets="400"))
    assert before.decision_input_digest == after.decision_input_digest
    assert before.forecast_output_digest == after.forecast_output_digest
    assert before.output_digest != after.output_digest
    assert (
        before.forecast_output_digest
        == replay_operating_scenarios(comparison_request().decision).output_digest
    )


def test_ambiguous_first_original_is_retained_as_refusal():
    request = comparison_request()
    first = request.filing_inventory[0]
    duplicate_time = first.model_copy(
        update={"accession_number": "0000000001-27-000002"}
    )
    inventory = (first, duplicate_time)
    result = replay_operating_comparison(
        request.model_copy(
            update={
                "filing_inventory": inventory,
                "filing_inventory_digest": sha256_digest(inventory),
            }
        )
    )
    assert all(
        label.status == "abstained"
        and "LABEL_FIRST_ORIGINAL_CONFLICT" in label.issue_codes
        for label in result.labels
    )
    assert all(row.signed_error is None for row in result.comparisons)


def test_earlier_amendment_cannot_replace_first_subsequent_original():
    request = comparison_request()
    amendment = request.filing_inventory[0].model_copy(
        update={
            "accession_number": "0000000001-27-000000",
            "available_at": datetime(2027, 1, 31, tzinfo=UTC),
            "form": "10-K/A",
            "is_amendment": True,
        }
    )
    inventory = (amendment, *request.filing_inventory)
    result = replay_operating_comparison(
        request.model_copy(
            update={
                "filing_inventory": inventory,
                "filing_inventory_digest": sha256_digest(inventory),
            }
        )
    )
    expected = replay_operating_comparison(request)
    assert result.labels == expected.labels
    assert result.comparisons == expected.comparisons


@pytest.mark.parametrize(
    "kind,code",
    [
        ("earlier_original", "LABEL_FIRST_ORIGINAL_MISMATCH"),
        ("target_period", "LABEL_TARGET_OR_BASIS_MISMATCH"),
        ("mixed_original", "LABEL_TARGET_OR_BASIS_MISMATCH"),
        ("corrupt_value", "SCENARIO_ORIGINAL_FACT_MISMATCH"),
        ("wrong_unit", "SCENARIO_ORIGINAL_FACT_MISMATCH"),
        ("missing_fact", "SCENARIO_FACT_MISSING"),
        ("future_available", "SCENARIO_ORIGINAL_SOURCE_INVALID"),
        ("conflict", "HISTORY_FACT_CONFLICT"),
    ],
)
def test_label_failures_are_retained_for_all_models_without_falling_forward(kind, code):
    request = comparison_request()
    label = request.label
    fact = next(
        f
        for f in label.facts
        if f.normalized_field == "current_assets" and f.period_end.year == 2026
    )
    if kind == "earlier_original":
        earlier = request.filing_inventory[0].model_copy(
            update={
                "accession_number": "0000000001-27-000000",
                "available_at": datetime(2027, 1, 31, tzinfo=UTC),
            }
        )
        inventory = (earlier, *request.filing_inventory)
        request = request.model_copy(
            update={
                "filing_inventory": inventory,
                "filing_inventory_digest": sha256_digest(inventory),
            }
        )
    elif kind == "target_period":
        target = label.periods[1].model_copy(update={"period_start": date(2026, 2, 1)})
        label = label.model_copy(update={"periods": (label.periods[0], target)})
    elif kind == "missing_fact":
        label = label.model_copy(
            update={"facts": tuple(f for f in label.facts if f != fact)}
        )
    elif kind == "conflict":
        original = label.source.originals[0]
        raw = next(
            f
            for f in original.report.facts
            if f.concept == fact.concept and f.instant == fact.instant
        )
        raw = raw.model_copy(
            update={"context_id": "conflicting-current-assets", "value": "999"}
        )
        report = original.report.model_copy(
            update={"facts": (*original.report.facts, raw)}
        )
        original = evaluate_original_issuer(
            report, source=original.source, decision_at=original.decision_at
        )
        source = compose_issuer_operating_source(
            (original,), valuation_timestamp=original.source.available_at
        )
        mapping = next(
            m for m in label.mappings if m.normalized_field == "current_assets"
        )
        candidates = parsed_facts_to_candidates(
            report,
            source=original.source,
            issuer_id=original.source.cik,
            normalized_field="current_assets",
            mapping=mapping,
        )
        extra = next(
            c.canonical_fact(quality=QualityStatus.PROVISIONAL)
            for c in candidates
            if c.value == Decimal(999)
        )
        label = label.model_copy(
            update={"source": source, "facts": (*label.facts, extra)}
        )
    else:
        changes = {
            "mixed_original": {"accession_number": "0000000001-28-000001"},
            "corrupt_value": {"value": Decimal(999)},
            "wrong_unit": {"unit": "xbrli:shares"},
            "future_available": {"available_at": datetime(2028, 1, 1, tzinfo=UTC)},
        }
        label = label.model_copy(
            update={
                "facts": tuple(
                    f.model_copy(update=changes[kind]) if f == fact else f
                    for f in label.facts
                )
            }
        )
    result = replay_operating_comparison(request.model_copy(update={"label": label}))
    assert len(result.labels) == 2 and len(result.comparisons) == 4
    assert all(
        label.status == "abstained" and code in label.issue_codes
        for label in result.labels
    )
    assert all(row.signed_error is None for row in result.comparisons)
    assert len(result.retained_label_fact_ids) == len(label.facts)


def test_unpaired_assumptions_retain_forecasts_and_no_comparison():
    request = comparison_request()
    scenarios = tuple(
        s.model_copy(update={"operating_asset_fraction": Decimal("0.5")})
        for s in request.label.scenarios
    )
    result = replay_operating_comparison(
        request.model_copy(
            update={"label": request.label.model_copy(update={"scenarios": scenarios})}
        )
    )
    assert len(result.comparisons) == 2
    assert all(
        "LABEL_PAIRED_ASSUMPTION_UNAVAILABLE" in row.issue_codes
        for row in result.comparisons
    )


def test_strict_policy_manifest_and_deterministic_atomic_replay(tmp_path):
    request = comparison_request()
    for updates in (
        {"decision_input_digest": "b" * 64},
        {"filing_inventory_digest": "b" * 64},
        {"policy_digest": "b" * 64},
    ):
        with pytest.raises(ValidationError):
            OperatingComparisonRequestV1.model_validate(
                {**request.model_dump(), **updates}
            )
    expected = replay_operating_comparison(request)
    with localcontext(Context(prec=7, rounding=ROUND_DOWN, Emin=-2, Emax=2)):
        assert replay_operating_comparison(request) == expected
    assert (
        OperatingComparisonRequestV1.model_validate_json(canonical_bytes(request))
        == request
    )
    assert expected.output_digest == sha256_digest(
        expected.model_dump(exclude={"output_digest"})
    )
    first = publish_operating_comparison(
        request, artifacts=ArtifactStore(tmp_path), execution={"exact_commit": "a" * 40}
    )
    before = {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.iterdir()
        if p.is_file()
    }
    repeat = publish_operating_comparison(
        request, artifacts=ArtifactStore(tmp_path), execution={"exact_commit": "a" * 40}
    )
    assert first["wrote"] and not repeat["wrote"]
    assert (
        first["input_digest"] == repeat["input_digest"]
        and first["output_digest"] == repeat["output_digest"]
    )
    assert all(
        not publication["wrote"] for publication in repeat["publications"].values()
    )
    assert before == {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.iterdir()
        if p.is_file()
    }
