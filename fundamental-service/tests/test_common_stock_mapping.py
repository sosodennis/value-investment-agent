"""Common-equity components preserve source scope without inferring class rights."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fundamental_service.accounting_roles import (
    AccountingComponentV1,
    AccountingRoleError,
    evaluate_period_rule,
)
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.automatic_mapping import (
    AutomaticMappingDecisionV1,
    automatic_mapping_proposal,
    automatic_mapping_proposals,
    verify_automatic_mapping_replay,
)
from fundamental_service.common_stock_mapping import COMMON_STOCK, select_common_stock
from fundamental_service.data_releases import (
    ArtifactRefV1,
    AutomaticMappingApprovalV1,
    DataReleaseError,
)
from fundamental_service.original_issuer import evaluate_original_issuer
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_automatic_mapping import approve, case, evaluate
from test_automatic_mapping_security import security_case, security_source
from test_issuer_operating_release import inventory

ROLE = "common_shares_outstanding"
CONCEPT = "us-gaap:CommonStockSharesOutstanding"
DIMENSIONS = (("us-gaap:StatementEquityComponentsAxis", "us-gaap:CommonStockMember"),)


def shares_case(tmp_path, *, change=None, extras=(), security=False):
    if security:
        request, store, roots = security_case(tmp_path)
    else:
        request, store, roots, _ = case(tmp_path)
    base = next(f for f in request.original.report.facts if f.instant is not None)
    component = base.model_copy(
        update={
            "concept": CONCEPT,
            "context_id": "common-equity-component",
            "is_numeric": True,
            "value": "7940000000",
            "unit": "xbrli:shares",
            "decimals": "-6",
            "namespace_uri": "http://fasb.org/us-gaap/2025",
            "dimensions": DIMENSIONS,
            "consolidation_scope": "segmented",
            "security_scope": "segmented",
            **(change or {}),
        }
    )
    facts = (
        *request.original.report.facts,
        component,
        *(component.model_copy(update=e) for e in extras),
    )
    report = request.original.report.model_copy(update={"facts": facts})
    original = evaluate_original_issuer(
        report, source=request.original.source, decision_at=request.original.decision_at
    )
    integrity = request.integrity.model_copy(
        update={
            "normalized_fact_count": len(facts),
            "archive_fact_count": len(facts),
            "normalized_fact_digest": fact_semantic_digest(report),
            "archive_fact_digest": fact_semantic_digest(report),
        }
    )
    publication = store.put_bytes_with_receipt(
        "common-stock-integrity-" + sha256_digest(integrity), canonical_bytes(integrity)
    )
    refs = tuple(
        sorted(
            (
                *(
                    r
                    for r in request.evidence_refs
                    if r.content_hash != sha256_digest(request.integrity)
                ),
                ArtifactRefV1(
                    artifact_id=publication.artifact.artifact_id,
                    content_hash=publication.artifact.content_hash,
                    media_type=publication.artifact.media_type,
                    role="synthetic-source-evidence",
                ),
            ),
            key=lambda r: r.artifact_id,
        )
    )
    proposal = automatic_mapping_proposal(
        ROLE, original=original, mapping_version=request.proposal.mapping_version
    )
    return (
        request.model_copy(
            update={
                "original": original,
                "integrity": integrity,
                "evidence_refs": refs,
                "proposal": proposal
                or request.proposal.model_copy(
                    update={"source_concept": COMMON_STOCK, "normalized_field": ROLE}
                ),
            }
        ),
        store,
        roots,
    )


@pytest.mark.parametrize("year", (2023, 2024, 2025, 2026))
@pytest.mark.parametrize("security", (False, True))
def test_component_signs_rebuilds_with_original_scope_and_reuses(
    tmp_path, year, security
):
    request, store, roots = shares_case(
        tmp_path,
        change={"namespace_uri": f"http://fasb.org/us-gaap/{year}"},
        extras=({"context_id": "coarse", "value": "7900000000", "decimals": "-8"},),
        security=security,
    )
    assert request.proposal.source_concept == COMMON_STOCK
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved", decision.reason_codes
    mapping = decision.mapping
    assert mapping.anchor_concept == COMMON_STOCK
    assert (
        mapping.accounting_rules.policy_version
        == "standard-common-equity-component-shares-v1"
    )
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=security_source(request) if security else request.original.source,
        issuer_id=request.original.source.cik,
        security_id="EXAMPLE" if security else None,
        normalized_field=ROLE,
        mapping=mapping,
    )
    assert len(candidates) == 1 and candidates[0].value == Decimal("7940000000")
    evidence = candidates[0].accounting_evidence
    assert evidence.source_facts[0].dimensions == DIMENSIONS
    assert evidence.source_facts[0].context_id == "common-equity-component"
    assert evidence.source_facts[0].decimals == "-6"
    assert evidence.period_rule.components[0].equity_component == "common_stock"
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    assert (
        verify_automatic_mapping_replay(approval, mapping, artifacts=store) == request
    )
    before = inventory(store.root)
    repeated = approve(request, store, roots)
    assert repeated.output_digest == receipt.output_digest
    assert inventory(store.root) == before
    assert all(
        not p.wrote
        for p in (
            repeated.input_publication,
            repeated.decision_publication,
            repeated.approval_publication,
        )
    )
    proposals = automatic_mapping_proposals(
        ROLE,
        original=request.original,
        mapping_version=request.proposal.mapping_version,
        observed_only=True,
    )
    assert len(proposals) == 1 and proposals[0].source_concept == COMMON_STOCK


@pytest.mark.parametrize(
    "change",
    (
        {"namespace_uri": "http://fasb.org/us-gaap/2022"},
        {"namespace_uri": "https://example.test/us-gaap/2025"},
        {"value": "-1"},
        {"value": "NaN"},
        {"value": "Infinity"},
        {"is_numeric": False},
        {"decimals": None},
        {"decimals": "INF"},
        {"entity_identifier": "999999"},
        {"entity_scheme": "https://example.test"},
        {"unit": "iso4217:USD"},
        {"security_scope": "issuer"},
        {"consolidation_scope": "consolidated"},
        {
            "instant": None,
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 12, 31),
        },
    ),
)
def test_invalid_component_keeps_refusal_without_signature(tmp_path, change):
    request, store, roots = shares_case(tmp_path, change=change)
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert receipt.approval_publication is None
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_COMMON_STOCK_COMPONENT_INVALID" in decision.reason_codes


@pytest.mark.parametrize(
    "dimensions",
    (
        (("us-gaap:StatementClassOfStockAxis", "example:ClassA"),),
        (("us-gaap:StatementBusinessSegmentsAxis", "example:Segment"),),
        (("us-gaap:StatementEquityComponentsAxis", "us-gaap:PreferredStockMember"),),
        (*DIMENSIONS, ("us-gaap:StatementClassOfStockAxis", "example:ClassA")),
    ),
)
def test_class_or_segment_is_not_an_issuer_common_equity_total(tmp_path, dimensions):
    request, store, _ = shares_case(tmp_path, change={"dimensions": dimensions})
    assert select_common_stock(request.original).rules is None
    assert evaluate(request, store).status == "abstain"


@pytest.mark.parametrize("direct_precision", ("-8", "0"))
def test_equivalent_dimensionless_representation_uses_highest_precision(
    tmp_path, direct_precision
):
    request, store, roots = shares_case(
        tmp_path,
        extras=(
            {
                "context_id": "dimensionless",
                "value": "7900000000" if direct_precision == "-8" else "7940000000",
                "decimals": direct_precision,
                "dimensions": (),
                "consolidation_scope": "consolidated",
                "security_scope": "issuer",
            },
        ),
    )
    decision = evaluate(request, store)
    assert decision.status == "approved", decision.reason_codes
    selection = select_common_stock(request.original)
    assert selection.selected[0].context_id == (
        "dimensionless" if direct_precision == "0" else "common-equity-component"
    )
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field=ROLE,
        mapping=decision.mapping,
    )
    assert candidates[0].value == Decimal("7940000000")
    receipt = approve(request, store, roots)
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    assert (
        verify_automatic_mapping_replay(approval, decision.mapping, artifacts=store)
        == request
    )


@pytest.mark.parametrize(
    "extra",
    (
        {"value": "7941000000", "decimals": "-6"},
        {"value": "8100000000", "decimals": "-8"},
        {
            "value": "7941000000",
            "dimensions": (),
            "consolidation_scope": "consolidated",
            "security_scope": "issuer",
        },
        {"namespace_uri": "http://fasb.org/us-gaap/2024"},
    ),
)
def test_conflicting_equivalent_representation_cannot_be_discarded(tmp_path, extra):
    request, store, _ = shares_case(
        tmp_path, extras=({"context_id": "conflict", **extra},)
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None


def test_future_period_and_missing_stay_unknown_but_explicit_zero_is_valid(tmp_path):
    request, _, _, _ = case(tmp_path / "missing")
    assert select_common_stock(request.original).rules is None
    future, store, _ = shares_case(
        tmp_path / "future", change={"instant": date(2026, 12, 31)}
    )
    assert "MAPPING_PERIOD_AFTER_ORIGINAL" in evaluate(future, store).reason_codes
    zero, store, _ = shares_case(tmp_path / "zero", change={"value": "0"})
    assert evaluate(zero, store).status == "approved"


def test_selection_is_order_independent_and_direct_bypass_refuses(tmp_path):
    request, store, _ = shares_case(tmp_path)
    reverse = request.original.model_copy(
        update={
            "report": request.original.report.model_copy(
                update={"facts": tuple(reversed(request.original.report.facts))}
            )
        }
    )
    assert select_common_stock(request.original) == select_common_stock(reverse)
    forged = request.model_copy(
        update={
            "proposal": request.proposal.model_copy(update={"source_concept": CONCEPT})
        }
    )
    decision = evaluate(forged, store)
    assert decision.status == "abstain"
    assert "MAPPING_STANDARD_REPRESENTATION_REQUIRED" in decision.reason_codes


@pytest.mark.parametrize(
    "change", ({"sign": -1}, {"balance_sheet_location": "other_current_liabilities"})
)
def test_common_equity_classification_cannot_be_negative_or_combined(change):
    with pytest.raises(ValidationError):
        AccountingComponentV1(
            parsed_fact_digest="a" * 64, equity_component="common_stock", **change
        )


def test_owner_rejects_role_scope_and_signature_tampering(tmp_path):
    request, store, roots = shares_case(tmp_path, security=True)
    receipt = approve(request, store, roots)
    mapping = evaluate(request, store).mapping
    rules = mapping.accounting_rules
    selection = select_common_stock(request.original)
    for altered in (
        rules.model_copy(update={"normalized_field": "preferred_claims"}),
        rules.model_copy(update={"unit": "iso4217:USD", "currency": "USD"}),
    ):
        with pytest.raises(AccountingRoleError):
            evaluate_period_rule(altered, rules.periods[0], selection.selected)
    removed = rules.periods[0].model_copy(
        update={
            "components": (
                rules.periods[0]
                .components[0]
                .model_copy(update={"equity_component": None}),
            )
        }
    )
    with pytest.raises(AccountingRoleError):
        evaluate_period_rule(rules, removed, selection.selected)
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    with pytest.raises(DataReleaseError):
        verify_automatic_mapping_replay(
            approval,
            mapping.model_copy(
                update={
                    "accounting_rules": rules.model_copy(
                        update={"policy_version": "forged"}
                    )
                }
            ),
            artifacts=store,
        )
    for security in (None, "OTHER"):
        with pytest.raises(SnapshotError):
            parsed_facts_to_candidates(
                request.original.report,
                source=security_source(request),
                issuer_id=request.original.source.cik,
                security_id=security,
                normalized_field=ROLE,
                mapping=mapping,
            )


def test_precision_failure_keeps_owning_reason(tmp_path):
    request, store, _ = shares_case(
        tmp_path,
        change={"value": "100000000000000000000000000000000", "decimals": "-2"},
        extras=(
            {
                "context_id": "large",
                "value": "100000000000000000000000000000000",
                "decimals": "0",
            },
        ),
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert "FACT_PRECISION_UNAVAILABLE" in decision.reason_codes


@pytest.mark.parametrize(
    "change",
    (
        {"concept": "us-gaap:CommonStockSharesIssued"},
        {"dimensions": (("us-gaap:StatementClassOfStockAxis", "example:ClassA"),)},
        {"namespace_uri": "https://example.test/us-gaap/2025"},
        {"consolidation_scope": "consolidated"},
        {"security_scope": "issuer"},
        {"entity_scheme": "https://example.test"},
    ),
)
def test_accounting_owner_rejects_forged_classification_scope(tmp_path, change):
    request, _, _ = shares_case(tmp_path)
    selection = select_common_stock(request.original)
    fact = selection.selected[0].model_copy(update=change)
    rule = selection.rules.periods[0]
    changed_rule = rule.model_copy(
        update={
            "components": (
                rule.components[0].model_copy(
                    update={"parsed_fact_digest": sha256_digest(fact)}
                ),
            )
        }
    )
    with pytest.raises(AccountingRoleError):
        evaluate_period_rule(selection.rules, changed_rule, (fact,))
