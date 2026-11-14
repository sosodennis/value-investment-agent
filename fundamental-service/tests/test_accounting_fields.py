"""Shared field observations retain ambiguity without approving financial inputs."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fundamental_service.accounting_fields import (
    AccountingFieldExtractionV1,
    AccountingFieldRequestV1,
    extract_accounting_fields,
)
from fundamental_service.automatic_mapping import automatic_mapping_proposals
from fundamental_service.facts import MappingObservationScopeV1
from fundamental_service.original_issuer import evaluate_original_issuer
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_original_issuer import DECISION, evaluate, original


def request(claim=None, fields=("revenue",), mappings=None):
    return AccountingFieldRequestV1(
        original=claim or evaluate(),
        normalized_fields=fields,
        mapping_version="review-v1",
        mappings=mappings,
    )


def with_observations(*observations):
    report, source = original()
    return evaluate_original_issuer(
        report.model_copy(update={"facts": (*report.facts, *observations)}),
        source=source,
        decision_at=DECISION,
    )


def test_extraction_reuses_registered_mapper_and_preserves_full_source_identity():
    supplied = request(fields=("operating_income", "revenue"))
    result = extract_accounting_fields(supplied)
    revenue = result.fields[1]
    expected = tuple(
        c
        for mapping in automatic_mapping_proposals(
            "revenue",
            mapping_version="review-v1",
            original=supplied.original,
        )
        for c in parsed_facts_to_candidates(
            supplied.original.report,
            source=supplied.original.source,
            issuer_id=supplied.original.source.cik,
            normalized_field="revenue",
            mapping=mapping,
        )
    )
    assert revenue.candidates == expected
    assert result.source == supplied.original.source
    assert result.original_evidence_digest == sha256_digest(supplied.original)
    assert revenue.status == "requires_semantic_review" and not revenue.conflicts
    candidate = revenue.candidates[0]
    assert candidate.period_start == date(2025, 1, 1)
    assert candidate.unit == "iso4217:USD" and candidate.scale == 0
    assert candidate.available_at == supplied.original.source.available_at
    assert candidate.mapping.status == "provisional"
    assert candidate.mapping.reviewer is None and candidate.security_id is None
    assert (
        AccountingFieldExtractionV1.model_validate_json(canonical_bytes(result))
        == result
    )


@pytest.mark.parametrize("mutation", ["period", "unit", "scope", "dimensions", "scale"])
def test_distinct_reported_scopes_are_not_false_value_conflicts(mutation):
    report, _ = original()
    revenue = report.facts[-1]
    changes = {
        "period": {"period_start": date(2024, 1, 1), "period_end": date(2024, 12, 31)},
        "unit": {"unit": "shares"},
        "scope": {"consolidation_scope": "unconsolidated"},
        "dimensions": {"dimensions": (("ex:Region", "ex:US"),)},
        "scale": {"scale": 3},
    }[mutation]
    changed = revenue.model_copy(
        update={"value": "999", "context_id": "other", **changes}
    )
    row = extract_accounting_fields(request(with_observations(changed))).fields[0]
    assert row.candidate_count == 2 and not row.conflicts
    assert row.status == "requires_semantic_review"


def test_cross_concept_conflicts_are_explicit_and_no_candidate_is_chosen():
    report, _ = original()
    conflicting = report.facts[-1].model_copy(
        update={
            "concept": "us-gaap:Revenues",
            "value": "999",
            "context_id": "other-tag",
        }
    )
    row = extract_accounting_fields(request(with_observations(conflicting))).fields[0]
    assert row.candidate_count == 2 and len(row.conflicts) == 1
    assert row.conflicts[0].candidate_ids == tuple(
        c.candidate_id for c in row.candidates
    )
    assert "FIELD_VALUE_CONFLICT_REQUIRES_REVIEW" in row.issue_codes
    assert {c.value for c in row.candidates} == {100, 999}


def test_equivalent_decimal_representations_are_not_conflicts():
    report, _ = original()
    equivalent = report.facts[-1].model_copy(
        update={"value": "100.00", "context_id": "duplicate"}
    )
    row = extract_accounting_fields(request(with_observations(equivalent))).fields[0]
    assert row.candidate_count == 2 and not row.conflicts


def test_reported_zero_is_retained_while_absent_and_unknown_roles_remain_unresolved():
    report, source = original()
    zero = report.facts[-1].model_copy(update={"value": "0"})
    claim = evaluate_original_issuer(
        report.model_copy(update={"facts": (*report.facts[:-1], zero)}),
        source=source,
        decision_at=DECISION,
    )
    rows = {
        row.field: row
        for row in extract_accounting_fields(
            request(
                claim, fields=("revenue", "operating_income", "unknown_accounting_role")
            )
        ).fields
    }
    assert rows["revenue"].candidates[0].value == Decimal(0)
    assert rows["revenue"].status == "requires_semantic_review"
    assert rows["operating_income"].candidates == ()
    unknown = rows["unknown_accounting_role"]
    assert unknown.status == "unresolved" and not unknown.proposals
    assert "NO_EXECUTABLE_MAPPING_PROPOSAL" in unknown.issue_codes


def test_declined_numeric_observations_remain_in_digest_bound_original():
    report, _ = original()
    invalid = report.facts[-1].model_copy(
        update={
            "value": "NaN",
            "concept": "us-gaap:OperatingIncomeLoss",
        }
    )
    claim = with_observations(invalid)
    assert claim.status == "matched"
    result = extract_accounting_fields(request(claim, fields=("operating_income",)))
    assert result.original_evidence_digest == sha256_digest(claim)
    assert claim.report.facts and invalid in claim.report.facts
    assert result.fields[0].status == "unresolved"
    assert (
        "NO_SOURCE_BOUND_CANDIDATE_IN_SUPPLIED_REPORT" in result.fields[0].issue_codes
    )


def test_future_original_is_retained_as_refusal_not_used_as_candidate():
    report, source = original()
    claim = evaluate_original_issuer(
        report,
        source=source,
        decision_at=source.available_at - timedelta(seconds=1),
    )
    result = extract_accounting_fields(request(claim))
    assert result.original_issue_codes == claim.issue_codes
    assert result.fields[0].status == "unresolved"
    assert "ORIGINAL_ISSUER_REFUSED" in result.fields[0].issue_codes


def test_supplied_mapping_uses_exact_scope_instead_of_registered_alternatives():
    claim = evaluate()
    mapping = automatic_mapping_proposals(
        "revenue", mapping_version="review-v1", original=claim
    )[0]
    # Revenues is absent; a supplied choice must not silently fall back to SalesRevenueNet.
    mapping = mapping.model_copy(update={"source_concept": "us-gaap:Revenues"})
    result = extract_accounting_fields(request(claim, mappings=(mapping,)))
    assert result.mapping_basis == "supplied_mappings"
    assert result.fields[0].proposals == (mapping,)
    assert not result.fields[0].candidates


def test_scoped_mapping_failure_retains_exact_mapping_id_and_reason():
    claim = evaluate()
    mapping = next(
        m
        for m in automatic_mapping_proposals(
            "revenue",
            mapping_version="review-v1",
            original=claim,
        )
        if m.source_concept == "us-gaap:SalesRevenueNet"
    )
    scope = MappingObservationScopeV1(
        issuer_id=claim.source.cik,
        accession_number=claim.source.accession_number,
        raw_content_hash=claim.source.content_hash,
        parser_input_hash=claim.source.parser_input_hash,
        parser_replay_digest="0" * 64,
        observation_digests=tuple(sorted(sha256_digest(f) for f in claim.report.facts)),
    )
    mapping = mapping.model_copy(update={"observation_scope": scope})
    row = extract_accounting_fields(request(claim, mappings=(mapping,))).fields[0]
    assert row.status == "unresolved" and not row.candidates
    assert row.extraction_failures[0].mapping_decision_id == mapping.decision_id
    assert row.extraction_failures[0].reason_code == "MAPPING_REPORT_MISMATCH"
    assert "MAPPING_REPORT_MISMATCH" in row.issue_codes


@pytest.mark.parametrize("change", ["field", "version", "duplicate"])
def test_supplied_mappings_cannot_change_requested_role_or_version(change):
    claim = evaluate()
    mapping = automatic_mapping_proposals(
        "revenue", mapping_version="review-v1", original=claim
    )[0]
    update = {
        "field": {"normalized_field": "other_role"},
        "version": {"mapping_version": "other-v1"},
        "duplicate": {},
    }[change]
    mappings = (
        (mapping, mapping)
        if change == "duplicate"
        else (mapping.model_copy(update=update),)
    )
    with pytest.raises(ValidationError):
        request(claim, mappings=mappings)


def test_copied_invalid_original_and_changed_output_are_rejected_at_boundary():
    supplied = request()
    forged = supplied.original.model_copy(update={"output_digest": "0" * 64})
    with pytest.raises(ValidationError, match="digest"):
        extract_accounting_fields(supplied.model_copy(update={"original": forged}))
    output = extract_accounting_fields(supplied).model_dump(mode="json")
    output["fields"][0]["status"] = "unresolved"
    with pytest.raises(ValidationError):
        AccountingFieldExtractionV1.model_validate(output)


def test_field_order_and_repeated_inputs_have_identical_bytes_and_digests():
    first = extract_accounting_fields(request(fields=("revenue", "operating_income")))
    second = extract_accounting_fields(request(fields=("operating_income", "revenue")))
    assert canonical_bytes(first) == canonical_bytes(second)
    assert first.input_digest == second.input_digest
    assert first.output_digest == second.output_digest
    assert first.output_digest == sha256_digest(
        first.model_dump(exclude={"output_digest"})
    )
    assert "model_inputs" in first.authority
    with pytest.raises(ValidationError, match="unique"):
        request(fields=("revenue", "revenue"))
