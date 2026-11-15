"""Aggregate disclosures retain scope without authorizing exact dilution."""

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
    verify_automatic_mapping_replay,
)
from fundamental_service.award_disclosures import (
    AWARD_DISCLOSURE_ROLES,
    AWARD_DISCLOSURE_FIELDS,
    AWARD_DISCLOSURE_DIMENSIONS,
)
from fundamental_service.award_disclosure_mapping import select_award_disclosure
from fundamental_service.data_releases import (
    ArtifactRefV1,
    AutomaticMappingApprovalV1,
    DataReleaseError,
)
from fundamental_service.equity_dilution import AWARD_FACT_FIELDS
from fundamental_service.original_issuer import evaluate_original_issuer
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_automatic_mapping import approve, case, evaluate
from test_automatic_mapping_security import security_case, security_source
from test_issuer_operating_release import inventory

ROLE, COST_ROLE = AWARD_DISCLOSURE_FIELDS
DIMENSIONS = AWARD_DISCLOSURE_DIMENSIONS


def award_case(tmp_path, *, role=ROLE, change=None, extras=(), security=False):
    if security:
        request, store, roots = security_case(tmp_path)
    else:
        request, store, roots, _ = case(tmp_path)
    base = next(f for f in request.original.report.facts if f.instant is not None)
    component = base.model_copy(
        update={
            "concept": AWARD_DISCLOSURE_ROLES[role].concept,
            "context_id": "restricted-stock-aggregate",
            "is_numeric": True,
            "value": "7940000000",
            "unit": AWARD_DISCLOSURE_ROLES[role].unit,
            "decimals": "-6",
            "namespace_uri": "http://fasb.org/us-gaap/2025",
            "dimensions": DIMENSIONS,
            "dimension_namespace_uris": (
                (
                    "us-gaap:AwardTypeAxis",
                    "http://fasb.org/us-gaap/2025",
                    "http://fasb.org/us-gaap/2025",
                ),
            ),
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
        "award-disclosure-integrity-" + sha256_digest(integrity),
        canonical_bytes(integrity),
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
        role, original=original, mapping_version=request.proposal.mapping_version
    )
    return (
        request.model_copy(
            update={
                "original": original,
                "integrity": integrity,
                "evidence_refs": refs,
                "proposal": proposal
                or request.proposal.model_copy(
                    update={
                        "source_concept": "classified:" + role,
                        "normalized_field": role,
                    }
                ),
            }
        ),
        store,
        roots,
    )


@pytest.mark.parametrize("role", AWARD_DISCLOSURE_FIELDS)
@pytest.mark.parametrize("security", (False, True))
def test_sign_rebuild_replay_preserves_scoped_aggregate_and_reuses(
    tmp_path, role, security
):
    request, store, roots = award_case(
        tmp_path,
        role=role,
        security=security,
        extras=({"context_id": "coarse", "value": "7900000000", "decimals": "-8"},),
    )
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved", decision.reason_codes
    mapping = decision.mapping
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=security_source(request) if security else request.original.source,
        issuer_id=request.original.source.cik,
        security_id="EXAMPLE" if security else None,
        normalized_field=role,
        mapping=mapping,
    )
    assert len(candidates) == 1 and candidates[0].value == Decimal("7940000000")
    evidence = candidates[0].accounting_evidence
    assert evidence.source_facts[0].dimensions == DIMENSIONS
    assert evidence.source_facts[0].context_id == "restricted-stock-aggregate"
    assert evidence.source_facts[0].decimals == "-6"
    assert (
        evidence.period_rule.components[0].award_disclosure_scope
        == "restricted_stock_nonvested_aggregate"
    )
    assert role not in AWARD_FACT_FIELDS
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    assert (
        verify_automatic_mapping_replay(approval, mapping, artifacts=store) == request
    )
    before = inventory(store.root)
    repeat = approve(request, store, roots)
    assert repeat.output_digest == receipt.output_digest
    assert inventory(store.root) == before
    assert not any(
        p.wrote
        for p in (
            repeat.input_publication,
            repeat.decision_publication,
            repeat.approval_publication,
        )
    )


@pytest.mark.parametrize(
    "change",
    (
        {"namespace_uri": "http://fasb.org/us-gaap/2024"},
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
        {"dimension_namespace_uris": ()},
        {
            "dimension_namespace_uris": (
                (
                    "us-gaap:AwardTypeAxis",
                    "https://example.test/rebound",
                    "http://fasb.org/us-gaap/2025",
                ),
            )
        },
        {
            "dimension_namespace_uris": (
                (
                    "us-gaap:AwardTypeAxis",
                    "http://fasb.org/us-gaap/2025",
                    "https://example.test/rebound",
                ),
            )
        },
        {
            "instant": None,
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 12, 31),
        },
    ),
)
def test_invalid_disclosure_retains_refusal_without_signing(tmp_path, change):
    request, store, roots = award_case(tmp_path, change=change)
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert receipt.approval_publication is None
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_AWARD_DISCLOSURE_INVALID" in decision.reason_codes


@pytest.mark.parametrize(
    "dimensions",
    (
        (),
        (("us-gaap:StatementBusinessSegmentsAxis", "example:Segment"),),
        (("us-gaap:AwardTypeAxis", "us-gaap:StockOptionsMember"),),
        (*DIMENSIONS, ("us-gaap:StatementClassOfStockAxis", "example:ClassA")),
    ),
)
def test_other_scopes_are_not_the_supported_aggregate(tmp_path, dimensions):
    request, store, _ = award_case(
        tmp_path, change={"dimensions": dimensions, "dimension_namespace_uris": ()}
    )
    assert select_award_disclosure(request.original, ROLE).rules is None
    assert "MAPPING_AWARD_DISCLOSURE_MISSING" in evaluate(request, store).reason_codes


@pytest.mark.parametrize(
    "extra",
    (
        {"value": "7941000000", "decimals": "-6"},
        {"value": "8100000000", "decimals": "-8"},
        {"namespace_uri": "http://fasb.org/us-gaap/2024"},
    ),
)
def test_conflicting_duplicate_cannot_be_selected_away(tmp_path, extra):
    request, store, _ = award_case(
        tmp_path, extras=({"context_id": "conflict", **extra},)
    )
    assert evaluate(request, store).status == "abstain"


def test_missing_future_and_zero_remain_distinct(tmp_path):
    missing, _, _, _ = case(tmp_path / "missing")
    assert select_award_disclosure(missing.original, ROLE).reason_codes == (
        "MAPPING_AWARD_DISCLOSURE_MISSING",
    )
    future, store, _ = award_case(
        tmp_path / "future", change={"instant": date(2026, 12, 31)}
    )
    assert "MAPPING_PERIOD_AFTER_ORIGINAL" in evaluate(future, store).reason_codes
    zero, store, _ = award_case(tmp_path / "zero", change={"value": "0"})
    assert evaluate(zero, store).status == "approved"


def test_order_independence_and_forged_exact_role_cannot_bypass_owner(tmp_path):
    request, store, roots = award_case(tmp_path)
    selection = select_award_disclosure(request.original, ROLE)
    reverse = request.original.model_copy(
        update={
            "report": request.original.report.model_copy(
                update={"facts": request.original.report.facts[::-1]}
            )
        }
    )
    assert selection == select_award_disclosure(reverse, ROLE)
    rules = selection.rules
    for role in (
        "equity_award_quantity",
        "equity_award_unrecognized_compensation",
        COST_ROLE,
    ):
        with pytest.raises(AccountingRoleError):
            evaluate_period_rule(
                rules.model_copy(update={"normalized_field": role}),
                rules.periods[0],
                selection.selected,
            )
    receipt = approve(request, store, roots)
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    mapping = evaluate(request, store).mapping
    with pytest.raises(DataReleaseError):
        verify_automatic_mapping_replay(
            approval,
            mapping.model_copy(update={"normalized_field": "equity_award_quantity"}),
            artifacts=store,
        )


@pytest.mark.parametrize(
    "change",
    (
        {"sign": -1},
        {"equity_component": "common_stock"},
        {"balance_sheet_location": "other_current_liabilities"},
        {"finance_lease_expense_location": "operating_expenses"},
    ),
)
def test_aggregate_classification_cannot_mix_scopes(change):
    with pytest.raises(ValidationError):
        AccountingComponentV1(
            parsed_fact_digest="a" * 64,
            award_disclosure_scope="restricted_stock_nonvested_aggregate",
            **change,
        )


@pytest.mark.parametrize(
    "change",
    (
        {
            "concept": "us-gaap:ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsGrantsInPeriod"
        },
        {"dimensions": ()},
        {"namespace_uri": "https://example.test/us-gaap/2025"},
        {"consolidation_scope": "consolidated"},
        {"security_scope": "issuer"},
        {"entity_scheme": "https://example.test"},
        {"value": "-1"},
    ),
)
def test_owner_rejects_tampered_source_even_with_recomputed_reference(tmp_path, change):
    request, _, _ = award_case(tmp_path)
    selection = select_award_disclosure(request.original, ROLE)
    fact = selection.selected[0].model_copy(update=change)
    period = selection.rules.periods[0]
    altered = period.model_copy(
        update={
            "components": (
                period.components[0].model_copy(
                    update={"parsed_fact_digest": sha256_digest(fact)}
                ),
            )
        }
    )
    with pytest.raises(AccountingRoleError):
        evaluate_period_rule(selection.rules, altered, (fact,))


def test_identical_representation_reuses_rule_for_another_issuer_and_period(tmp_path):
    request, _, _ = award_case(tmp_path)
    original = request.original
    alternate = original.model_copy(
        update={
            "source": original.source.model_copy(update={"cik": "0000000002"}),
            "report": original.report.model_copy(
                update={
                    "facts": tuple(
                        fact.model_copy(update={"entity_identifier": "2"})
                        for fact in original.report.facts
                    )
                }
            ),
        }
    )
    first = select_award_disclosure(original, ROLE)
    second = select_award_disclosure(alternate, ROLE)
    assert second.rules is not None
    assert second.rules.policy_version == first.rules.policy_version
    assert second.rules.issuer_id == "0000000002"
    assert tuple(f.value for f in second.selected) == tuple(
        f.value for f in first.selected
    )
    assert (
        second.rules.periods[0].components[0].award_disclosure_scope
        == first.rules.periods[0].components[0].award_disclosure_scope
    )
    prior = original.model_copy(
        update={
            "report": original.report.model_copy(
                update={
                    "facts": tuple(
                        fact.model_copy(
                            update={
                                "instant": fact.instant.replace(
                                    year=fact.instant.year - 1
                                )
                            }
                        )
                        if fact.concept == AWARD_DISCLOSURE_ROLES[ROLE].concept
                        else fact
                        for fact in original.report.facts
                    )
                }
            )
        }
    )
    previous = select_award_disclosure(prior, ROLE)
    assert previous.rules is not None
    assert previous.rules.policy_version == first.rules.policy_version
    assert previous.selected[0].instant.year == first.selected[0].instant.year - 1
