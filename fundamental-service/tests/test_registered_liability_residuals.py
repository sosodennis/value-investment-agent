"""Exhaustive source partitions must balance before any zero claim is admitted."""

from datetime import date
from decimal import Decimal, localcontext

import pytest

from fundamental_service import registered_liability_residuals as policy
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


@pytest.fixture(
    params=["long_term_interest_bearing_debt", "current_interest_bearing_debt"]
)
def principal_role(request):
    return request.param


def liability_case(tmp_path, monkeypatch, *, role=None, change=None):
    template, _, _, _ = case(tmp_path / "template")
    base = next(f for f in template.original.report.facts if f.is_numeric)
    role = role or "long_term_interest_bearing_debt"
    partition = next(p for p in policy.PARTITIONS if role in p.roles)
    amounts = (
        ((2024, ("100", "80", "20")), (2025, ("90", "60", "30")))
        if len(partition.components) == 3
        else ((2024, ("100", "40", "40", "20")), (2025, ("90", "30", "30", "30")))
    )
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
        for year, values in amounts
        for (concept, _), value in zip(partition.components, values, strict=True)
    ]
    if change:
        facts = change(facts)
    request, store, roots, bundle = case(
        tmp_path / "actual",
        extra=tuple(facts),
        proposal_changes={
            "source_concept": partition.concept,
            "normalized_field": role,
        },
    )
    source = request.original.source
    monkeypatch.setattr(
        policy,
        "_ORIGINALS",
        {
            (source.cik, source.accession_number): policy.OriginalClassification(
                source.parser_input_hash,
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
    partition = next(p for p in policy.PARTITIONS if role in p.roles)
    assert proposal.source_concept == partition.concept
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
        == {concept for concept, _ in partition.components}
        and len(c.accounting_evidence.source_facts) == len(partition.components)
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
    tmp_path, monkeypatch, changes, principal_role
):
    request, store, _, _ = liability_case(
        tmp_path,
        monkeypatch,
        role=principal_role,
        change=lambda facts: [facts[0].model_copy(update=changes), *facts[1:]],
    )
    result = evaluate(request, store)
    assert result.status == "abstain" and result.mapping is None
    prefix = next(
        p.reason_prefix for p in policy.PARTITIONS if principal_role in p.roles
    )
    assert prefix + "_COMPONENT_INVALID" in result.reason_codes


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
    partition = next(p for p in policy.PARTITIONS if role in p.roles)
    assert partition.reason_prefix + "_RESIDUAL_UNALLOCATED" in result.reason_codes


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
    tmp_path, monkeypatch, change, reason, principal_role
):
    request, store, _, _ = liability_case(
        tmp_path, monkeypatch, change=change, role=principal_role
    )
    result = evaluate(request, store)
    assert result.mapping is None and result.status == "abstain"
    prefix = next(
        p.reason_prefix for p in policy.PARTITIONS if principal_role in p.roles
    )
    assert reason.replace("MAPPING_NONCURRENT", prefix) in result.reason_codes


def test_unregistered_changed_and_future_originals_refuse(
    tmp_path, monkeypatch, principal_role
):
    request, _, _, _ = liability_case(tmp_path, monkeypatch, role=principal_role)
    original = request.original
    role = request.proposal.normalized_field
    prefix = next(p.reason_prefix for p in policy.PARTITIONS if role in p.roles)
    for changes, reason in (
        (
            {"source": original.source.model_copy(update={"cik": "0009999999"})},
            "MAPPING_NONCURRENT_SCOPE_UNREVIEWED",
        ),
        (
            {
                "source": original.source.model_copy(
                    update={"parser_input_hash": "f" * 64}
                )
            },
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
        assert policy.select_registered_liability_residual(
            changed, role
        ).reason_codes == (reason.replace("MAPPING_NONCURRENT", prefix),)
        assert (
            automatic_mapping_proposal(role, original=changed, mapping_version="test")
            is None
        )
    assert (
        policy.select_registered_liability_residual(
            original, "finance_lease_cost"
        ).rules
        is None
    )


def test_equivalent_duplicates_order_and_decimal_context_preserve_mapping(
    tmp_path, monkeypatch, principal_role
):
    request, store, _, _ = liability_case(
        tmp_path,
        monkeypatch,
        role=principal_role,
        change=lambda facts: [*facts, facts[0]],
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


def test_current_partition_cannot_authorize_noncurrent_or_operating_scope(
    tmp_path, monkeypatch
):
    request, store, _, _ = liability_case(
        tmp_path, monkeypatch, role="current_interest_bearing_debt"
    )
    assert evaluate(request, store).status == "approved"
    for role in (
        "accrued_operating_liabilities",
        "finance_lease_cost",
        "convertible_instruments",
        "preferred_claims",
        "other_share_classes",
    ):
        assert (
            automatic_mapping_proposal(
                role, original=request.original, mapping_version="test"
            )
            is None
        )
    wrong = request.model_copy(
        update={
            "proposal": request.proposal.model_copy(
                update={
                    "source_concept": policy.NONCURRENT_LIABILITY_RESIDUAL,
                }
            )
        }
    )
    assert evaluate(wrong, store).status == "abstain"


def test_duplicate_with_another_namespace_cannot_hide_behind_equivalent_amount(
    tmp_path, monkeypatch, principal_role
):
    request, store, _, _ = liability_case(
        tmp_path,
        monkeypatch,
        role=principal_role,
        change=lambda facts: [
            *facts,
            facts[0].model_copy(
                update={
                    "namespace_uri": "http://fasb.org/us-gaap/2023",
                }
            ),
        ],
    )
    result = evaluate(request, store)
    prefix = next(
        p.reason_prefix for p in policy.PARTITIONS if principal_role in p.roles
    )
    assert result.status == "abstain"
    assert prefix + "_COMPONENT_INVALID" in result.reason_codes
