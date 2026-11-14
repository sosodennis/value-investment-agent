"""Original-bound case compilation preserves formal results and refusals."""

import sys
from pathlib import Path

import pytest

from fundamental_service.facts import MappingObservationScopeV1
from fundamental_service.operating_labels import replay_operating_comparison
from fundamental_service.operating_scenarios import replay_operating_scenarios
from fundamental_service.operating_label_contracts import OperatingComparisonRequestV1
from fundamental_service.original_issuer import evaluate_original_issuer
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_operating_labels import comparison_request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import compile_operating_case as compiler  # noqa: E402


def observation_plan(request):
    mappings = []
    for original in request.source.originals:
        for mapping in request.mappings:
            observations = tuple(
                sorted(
                    sha256_digest(fact)
                    for fact in original.report.facts
                    if fact.concept == mapping.source_concept
                )
            )
            if not observations:
                continue
            scope = MappingObservationScopeV1(
                issuer_id=original.source.cik,
                accession_number=original.source.accession_number,
                raw_content_hash=original.source.content_hash,
                parser_input_hash=original.source.parser_input_hash,
                parser_replay_digest=original.report.replay_digest(),
                observation_digests=observations,
            )
            mappings.append(
                mapping.model_copy(
                    update={
                        "decision_id": mapping.decision_id
                        + "-"
                        + original.source.accession_number,
                        "observation_scope": scope,
                    }
                )
            )
    return compiler.ObservationPlan(
        originals=request.source.originals,
        valuation_timestamp=request.source.valuation_timestamp,
        mapping_version=request.mapping_version,
        mappings=tuple(mappings),
        calendars=tuple(
            period.model_dump(exclude={"fact_ids"}) for period in request.periods
        ),
        scenarios=request.scenarios,
        source_selection_policy=request.source_selection_policy,
        scope_assumptions=(
            "Explicit source/period scope retained for a conditional test; no accounting approval or observed-zero claim.",
        ),
        scope_evidence_digests=request.scope_assumption_evidence_digests,
    )


def case_plan():
    request = comparison_request()
    return request, compiler.CasePlan(
        decision=observation_plan(request.decision),
        label=observation_plan(request.label),
        filing_inventory=request.filing_inventory,
        inventory_evidence_digest=request.inventory_evidence_digest,
        model_versions=request.decision.model_versions,
        protocol_version=request.protocol_version,
    )


def compiled_request(plan):
    result = compiler.compile_case(plan)
    return OperatingComparisonRequestV1.model_validate_json(
        canonical_bytes(result["request"])
    )


def test_formal_forecast_label_error_parity_and_repeat():
    original, plan = case_plan()
    before = canonical_bytes(plan)
    first = compiler.compile_case(plan)
    assert canonical_bytes(first) == canonical_bytes(compiler.compile_case(plan))
    assert canonical_bytes(plan) == before
    request = compiled_request(plan)
    expected, actual = map(replay_operating_comparison, (original, request))
    expected_forecast, actual_forecast = map(
        replay_operating_scenarios, (original.decision, request.decision)
    )
    assert [
        (r.status, [(n.node_id, n.value) for n in r.nodes], r.issue_codes)
        for r in actual_forecast.results
    ] == [
        (r.status, [(n.node_id, n.value) for n in r.nodes], r.issue_codes)
        for r in expected_forecast.results
    ]
    assert [label.realized_fcff for label in actual.labels] == [
        label.realized_fcff for label in expected.labels
    ]
    assert [(e.status, e.signed_error, e.issue_codes) for e in actual.comparisons] == [
        (e.status, e.signed_error, e.issue_codes) for e in expected.comparisons
    ]
    assert actual.supported_history_threshold is None
    assert request.label.source.originals[0] not in request.decision.source.originals
    assert all(fact.quality.value == "provisional" for fact in request.decision.facts)
    extracted = first["decision_extractions"]
    assert sum(row.candidate_count for p in extracted for row in p.fields) == len(
        request.decision.facts
    )


@pytest.mark.parametrize("fault", ["approved", "unscoped", "duplicate", "version"])
def test_mapping_plans_cannot_grant_authority_or_change_scope(fault):
    _, plan = case_plan()
    mapping = plan.decision.mappings[0]
    changes = {
        "approved": {"status": "approved", "confidence": "high"},
        "unscoped": {"observation_scope": None},
        "version": {"mapping_version": "other"},
    }
    mappings = (
        (*plan.decision.mappings, mapping)
        if fault == "duplicate"
        else (mapping.model_copy(update=changes[fault]), *plan.decision.mappings[1:])
    )
    altered = plan.model_copy(
        update={"decision": plan.decision.model_copy(update={"mappings": mappings})}
    )
    with pytest.raises(ValueError):
        compiler.compile_case(altered)


def test_missing_role_fails_without_zero_imputation():
    _, plan = case_plan()
    altered = plan.model_copy(
        update={
            "decision": plan.decision.model_copy(
                update={
                    "mappings": tuple(
                        m
                        for m in plan.decision.mappings
                        if m.normalized_field != "depreciation_and_amortization"
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError, match="every selected observation"):
        compiler.compile_case(altered)


@pytest.mark.parametrize("fault", ["future", "amendment"])
def test_original_availability_and_amendment_refusals(fault):
    _, plan = case_plan()
    original = plan.decision.originals[0]
    source = (
        original.source.model_copy(
            update={
                "is_amendment": True,
                "form": "10-K/A",
            }
        )
        if fault == "amendment"
        else original.source.model_copy(
            update={
                "available_at": original.source.available_at.replace(year=2035),
                "captured_at": original.source.captured_at.replace(year=2035),
            }
        )
    )
    changed = evaluate_original_issuer(
        original.report, source=source, decision_at=original.decision_at
    )
    altered = plan.model_copy(
        update={"decision": plan.decision.model_copy(update={"originals": (changed,)})}
    )
    with pytest.raises(ValueError):
        compiler.compile_case(altered)


def test_segmented_candidates_remain_auditable_without_entering_issuer_inputs():
    from fundamental_service.contracts import DimensionV1

    _, plan = case_plan()
    original = plan.decision.originals[0]
    fact = next(
        f for f in original.report.facts if f.concept == "us-gaap:AssetsCurrent"
    )
    segment = fact.model_copy(
        update={
            "dimensions": (
                ("us-gaap:StatementBusinessSegmentsAxis", "test:SegmentMember"),
            ),
            "consolidation_scope": "segmented",
            "security_scope": "segmented",
        }
    )
    # Parsed dimensions are plain pairs; the canonical converter owns typed dimensions.
    assert DimensionV1(name=segment.dimensions[0][0], member=segment.dimensions[0][1])
    changed = evaluate_original_issuer(
        original.report.model_copy(update={"facts": (*original.report.facts, segment)}),
        source=original.source,
        decision_at=original.decision_at,
    )
    seed = comparison_request()
    replacement = observation_plan(
        seed.decision.model_copy(
            update={
                "source": seed.decision.source.model_copy(
                    update={"originals": (changed,)}
                )
            }
        )
    )
    result = compiler.compile_case(plan.model_copy(update={"decision": replacement}))
    request = result["request"]
    assert len(result["excluded_nonissuer_candidates"]["decision"]) == 1
    assert all(not f.context.dimensions for f in request.decision.facts)
    assert (
        sum(
            row.candidate_count
            for p in result["decision_extractions"]
            for row in p.fields
        )
        == len(request.decision.facts) + 1
    )


def test_equal_precision_conflict_is_retained_and_refused():
    _, plan = case_plan()
    original = plan.decision.originals[0]
    fact = next(
        f for f in original.report.facts if f.concept == "us-gaap:AssetsCurrent"
    )
    changed_fact = fact.model_copy(update={"value": "99999999"})
    changed = evaluate_original_issuer(
        original.report.model_copy(
            update={"facts": (*original.report.facts, changed_fact)}
        ),
        source=original.source,
        decision_at=original.decision_at,
    )
    # Rebind every plan observation to the changed original, retaining both values.
    seed, _ = case_plan()
    changed_request = seed.decision.model_copy(
        update={
            "source": seed.decision.source.model_copy(update={"originals": (changed,)})
        }
    )
    changed_plan = observation_plan(changed_request)
    observations, extractions = compiler.compile_observations(changed_plan)
    assert any(row.conflicts for p in extractions for row in p.fields)
    with pytest.raises(ValueError):
        compiler.compile_case(plan.model_copy(update={"decision": changed_plan}))
    assert len(observations.facts) == len(seed.decision.facts) + 1


def test_wrong_first_label_remains_a_formal_label_refusal():
    _, plan = case_plan()
    first = plan.filing_inventory[0]
    inventory = (first.model_copy(update={"accession_number": "0000000001-27-000000"}),)
    request = compiled_request(plan.model_copy(update={"filing_inventory": inventory}))
    result = replay_operating_comparison(request)
    assert all(
        "LABEL_FIRST_ORIGINAL_MISMATCH" in label.issue_codes for label in result.labels
    )
    assert all(label.realized_fcff is None for label in result.labels)


def test_unknown_model_version_refuses_before_forecast():
    _, plan = case_plan()
    with pytest.raises(ValueError, match="requires executable version"):
        compiler.compile_case(
            plan.model_copy(
                update={
                    "model_versions": {
                        **plan.model_versions,
                        "fcff_dcf": "unimplemented-v999",
                    }
                }
            )
        )
