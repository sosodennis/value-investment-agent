"""Exhaustive source partitions must balance before any zero claim is admitted."""

from datetime import date
from decimal import Decimal, localcontext

import pytest

from fundamental_service import registered_noncurrent_liabilities as policy
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.automatic_mapping import (
    AutomaticMappingApprovalV1,
    AutomaticMappingDecisionV1,
    automatic_mapping_proposal,
    verify_automatic_mapping_replay,
)
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import sha256_digest
from test_automatic_mapping import approve, case, evaluate
from test_issuer_operating_release import inventory


def liability_case(tmp_path, monkeypatch, *, role=None, change=None):
    template, _, _, _ = case(tmp_path / "template")
    base = next(f for f in template.original.report.facts if f.is_numeric)
    facts = [
        base.model_copy(
            update={
                "concept": concept,
                "context_id": f"liability-{year}",
                "value": value,
                "instant": date(year, 12, 31),
                "period_start": None,
                "period_end": None,
                "decimals": "0",
            }
        )
        for year, amounts in ((2024, ("100", "80", "20")), (2025, ("90", "60", "30")))
        for (concept, _), value in zip(policy.COMPONENTS, amounts, strict=True)
    ]
    if change:
        facts = change(facts)
    request, store, roots, bundle = case(
        tmp_path / "actual",
        extra=tuple(facts),
        proposal_changes={
            "source_concept": policy.NONCURRENT_LIABILITY_RESIDUAL,
            "normalized_field": role or "long_term_interest_bearing_debt",
        },
    )
    source = request.original.source
    monkeypatch.setattr(
        policy,
        "_ORIGINALS",
        {
            (source.cik, source.accession_number): policy.OriginalClassification(
                source.content_hash,
                fact_semantic_digest(request.original.report),
                (date(2024, 12, 31), date(2025, 12, 31)),
            )
        },
    )
    return request, store, roots, bundle


@pytest.mark.parametrize("role", sorted(policy.ROLES))
def test_zero_partition_retains_all_components_and_signed_replay(
    tmp_path, monkeypatch, role
):
    request, store, roots, _ = liability_case(tmp_path, monkeypatch, role=role)
    proposal = automatic_mapping_proposal(
        role,
        original=request.original,
        mapping_version=request.proposal.mapping_version,
    )
    assert proposal.source_concept == policy.NONCURRENT_LIABILITY_RESIDUAL
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved"
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field=role,
        mapping=decision.mapping,
    )
    assert {f.instant.year: f.value for f in candidates} == {
        2024: Decimal("0"),
        2025: Decimal("0"),
    }
    assert all(
        c.accounting_evidence.period_rule.disposition == "derived"
        and {f.concept for f in c.accounting_evidence.source_facts}
        == {concept for concept, _ in policy.COMPONENTS}
        and len(c.accounting_evidence.source_facts) == 3
        for c in candidates
    )
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    before = inventory(store.root)
    assert (
        verify_automatic_mapping_replay(approval, decision.mapping, artifacts=store)
        == request
    )
    repeat = approve(request, store, roots)
    assert repeat.output_digest == receipt.output_digest
    assert not any(
        publication.wrote
        for publication in (
            repeat.input_publication,
            repeat.decision_publication,
            repeat.approval_publication,
        )
    )
    assert inventory(store.root) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"unit": "iso4217:EUR"},
        {"namespace_uri": "https://example.test/extension"},
        {"entity_identifier": "9999999"},
        {"entity_scheme": "https://example.test/issuer"},
        {"consolidation_scope": "unconsolidated"},
        {"security_scope": "foreign-security"},
        {"decimals": None},
        {"decimals": "-3"},
        {"value": "NaN"},
        {"value": "-1"},
        {"period_start": date(2024, 1, 1)},
    ],
)
def test_invalid_partition_component_cannot_establish_zero(
    tmp_path, monkeypatch, changes
):
    request, store, _, _ = liability_case(
        tmp_path,
        monkeypatch,
        change=lambda facts: [facts[0].model_copy(update=changes), *facts[1:]],
    )
    result = evaluate(request, store)
    assert result.status == "abstain" and result.mapping is None
    assert "MAPPING_NONCURRENT_COMPONENT_INVALID" in result.reason_codes


@pytest.mark.parametrize("value", ["99", "101"])
@pytest.mark.parametrize("role", sorted(policy.ROLES))
def test_nonzero_residual_is_not_allocated_to_either_role(
    tmp_path, monkeypatch, value, role
):
    request, store, _, _ = liability_case(
        tmp_path,
        monkeypatch,
        role=role,
        change=lambda facts: [facts[0].model_copy(update={"value": value}), *facts[1:]],
    )
    result = evaluate(request, store)
    assert result.mapping is None and result.status == "abstain"
    assert "MAPPING_NONCURRENT_RESIDUAL_UNALLOCATED" in result.reason_codes


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda fs: fs[1:], "MAPPING_NONCURRENT_COMPONENT_MISSING"),
        (
            lambda fs: [*fs, fs[0].model_copy(update={"value": "101"})],
            "MAPPING_OBSERVATION_CONFLICT",
        ),
        (
            lambda fs: [
                fs[0].model_copy(update={"instant": date(2024, 6, 30)}),
                *fs[1:],
            ],
            "MAPPING_NONCURRENT_COMPONENT_MISSING",
        ),
        (
            lambda fs: [
                fs[0].model_copy(
                    update={"namespace_uri": "http://fasb.org/us-gaap/2023"}
                ),
                *fs[1:],
            ],
            "MAPPING_NONCURRENT_COMPONENT_INVALID",
        ),
    ],
)
def test_incomplete_conflicting_and_misaligned_partitions_retain_reason(
    tmp_path, monkeypatch, change, reason
):
    request, store, _, _ = liability_case(tmp_path, monkeypatch, change=change)
    result = evaluate(request, store)
    assert result.mapping is None and result.status == "abstain"
    assert reason in result.reason_codes


def test_unregistered_changed_and_future_originals_refuse(tmp_path, monkeypatch):
    request, _, _, _ = liability_case(tmp_path, monkeypatch)
    original = request.original
    role = request.proposal.normalized_field
    for changes, reason in (
        (
            {"source": original.source.model_copy(update={"cik": "0009999999"})},
            "MAPPING_NONCURRENT_SCOPE_UNREVIEWED",
        ),
        (
            {"source": original.source.model_copy(update={"content_hash": "f" * 64})},
            "MAPPING_NONCURRENT_SCOPE_UNREVIEWED",
        ),
        (
            {
                "report": original.report.model_copy(
                    update={"facts": original.report.facts[1:]}
                )
            },
            "MAPPING_NONCURRENT_SOURCE_MISMATCH",
        ),
        ({"report_period_end": date(2024, 12, 31)}, "MAPPING_PERIOD_AFTER_ORIGINAL"),
    ):
        changed = original.model_copy(update=changes)
        assert policy.select_registered_noncurrent_liabilities(
            changed, role
        ).reason_codes == (reason,)
        assert (
            automatic_mapping_proposal(role, original=changed, mapping_version="test")
            is None
        )
    assert (
        policy.select_registered_noncurrent_liabilities(
            original, "finance_lease_cost"
        ).rules
        is None
    )


def test_equivalent_duplicates_order_and_decimal_context_preserve_mapping(
    tmp_path, monkeypatch
):
    request, store, _, _ = liability_case(
        tmp_path, monkeypatch, change=lambda facts: [*facts, facts[0]]
    )
    before = evaluate(request, store)
    assert before.status == "approved"
    reordered = request.model_copy(
        update={
            "original": request.original.model_copy(
                update={
                    "report": request.original.report.model_copy(
                        update={"facts": tuple(reversed(request.original.report.facts))}
                    )
                }
            )
        }
    )
    with localcontext() as context:
        context.prec = 2
        after = evaluate(reordered, store)
    assert sha256_digest(after.mapping) == sha256_digest(before.mapping)
    assert after.eligible_observation_digests == before.eligible_observation_digests
