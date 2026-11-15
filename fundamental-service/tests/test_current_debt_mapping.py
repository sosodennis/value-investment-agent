"""Original-term totals supply current debt only as a complete disjoint pair."""

from datetime import date
from decimal import Decimal

import pytest

from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.automatic_mapping import (
    AutomaticMappingDecisionV1,
    automatic_mapping_proposal,
    verify_automatic_mapping_replay,
)
from fundamental_service.current_debt_mapping import CURRENT_DEBT
from fundamental_service.data_releases import (
    ArtifactRefV1,
    AutomaticMappingApprovalV1,
    DataReleaseError,
)
from fundamental_service.original_issuer import evaluate_original_issuer
from fundamental_service.registered_liability_residuals import (
    CURRENT_LIABILITY_RESIDUAL,
)
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_automatic_mapping import approve, case, evaluate
from test_automatic_mapping_security import security_case, security_source
from test_issuer_operating_release import inventory

ROLE = "current_interest_bearing_debt"
CONCEPTS = ("us-gaap:LongTermDebtCurrent", "us-gaap:ShortTermBorrowings")


def current_debt_case(
    tmp_path, *, changes=None, omitted=(), extras=(), security=False, reverse=False
):
    if security:
        request, store, roots = security_case(tmp_path)
    else:
        request, store, roots, _ = case(tmp_path)
    base = next(
        f
        for f in request.original.report.facts
        if f.is_numeric and f.instant is not None and f.unit == "iso4217:USD"
    )
    components = tuple(
        base.model_copy(
            update={
                "concept": concept,
                "context_id": f"component-{index}",
                "value": value,
                "decimals": "-6",
                "namespace_uri": "http://fasb.org/us-gaap/2025",
                **((changes or {}).get(index, {})),
            }
        )
        for index, (concept, value) in enumerate(
            zip(CONCEPTS, ("3542000000", "6596000000"))
        )
        if index not in omitted
    )
    facts = (
        *request.original.report.facts,
        *components,
        *(components[0].model_copy(update=x) for x in extras),
    )
    report = request.original.report.model_copy(
        update={"facts": tuple(reversed(facts)) if reverse else facts}
    )
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
        "current-debt-integrity-" + sha256_digest(integrity), canonical_bytes(integrity)
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
                    update={"source_concept": CURRENT_DEBT, "normalized_field": ROLE}
                ),
            }
        ),
        store,
        roots,
    )


@pytest.mark.parametrize("year", (2023, 2024, 2025, 2026))
@pytest.mark.parametrize("security", (False, True))
def test_complete_totals_sign_rebuild_replay_and_reuse(tmp_path, year, security):
    request, store, roots = current_debt_case(
        tmp_path,
        security=security,
        changes={
            i: {"namespace_uri": f"http://fasb.org/us-gaap/{year}"} for i in (0, 1)
        },
        extras=(
            {"context_id": "coarse-current", "value": "3500000000", "decimals": "-8"},
        ),
    )
    assert request.proposal.source_concept == CURRENT_DEBT
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved", decision.reason_codes
    mapping = decision.mapping
    assert mapping.anchor_concept == CURRENT_DEBT
    assert (
        mapping.accounting_rules.policy_version
        == "standard-current-debt-original-term-totals-v1"
    )
    assert len(decision.eligible_observation_digests) == 2
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=security_source(request) if security else request.original.source,
        issuer_id=request.original.source.cik,
        security_id="EXAMPLE" if security else None,
        normalized_field=ROLE,
        mapping=mapping,
    )
    assert len(candidates) == 1 and candidates[0].value == Decimal("10138000000")
    assert candidates[0].decimals is None
    assert {f.decimals for f in candidates[0].accounting_evidence.source_facts} == {
        "-6"
    }
    assert len(candidates[0].accounting_evidence.rule_set.periods[0].components) == 2
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
    assert all(
        not p.wrote
        for p in (
            repeat.input_publication,
            repeat.decision_publication,
            repeat.approval_publication,
        )
    )


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
        {"unit": "iso4217:EUR"},
        {"security_scope": "segmented"},
        {"consolidation_scope": "segmented"},
        {
            "instant": None,
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 12, 31),
        },
    ),
)
def test_invalid_component_retains_refusal_without_approval(tmp_path, change):
    request, store, roots = current_debt_case(tmp_path, changes={0: change})
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_CURRENT_DEBT_COMPONENT_INVALID" in decision.reason_codes
    receipt = approve(request, store, roots)
    assert receipt.approval_publication is None
    assert (
        AutomaticMappingDecisionV1.model_validate_json(
            store.read(receipt.decision_publication.artifact.artifact_id)
        )
        == decision
    )


@pytest.mark.parametrize("missing", (0, 1))
def test_partial_pair_and_residual_override_cannot_infer_zero(tmp_path, missing):
    request, store, _ = current_debt_case(tmp_path, omitted=(missing,))
    assert request.proposal.source_concept == CURRENT_DEBT
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert "MAPPING_CURRENT_DEBT_COMPONENT_MISSING" in decision.reason_codes
    overridden = request.model_copy(
        update={
            "proposal": request.proposal.model_copy(
                update={"source_concept": CURRENT_LIABILITY_RESIDUAL}
            )
        }
    )
    assert (
        "MAPPING_DEBT_DIRECT_REPRESENTATION_REQUIRED"
        in evaluate(overridden, store).reason_codes
    )


@pytest.mark.parametrize(
    "other",
    (
        "us-gaap:CommercialPaper",
        "us-gaap:DebtCurrent",
        "us-gaap:LongTermDebtAndFinanceLeaseObligationsCurrent",
    ),
)
def test_subtotal_or_lease_inclusive_tag_cannot_replace_component(tmp_path, other):
    request, store, _ = current_debt_case(tmp_path, changes={1: {"concept": other}})
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert "MAPPING_CURRENT_DEBT_COMPONENT_MISSING" in decision.reason_codes


def test_mismatched_instants_namespaces_and_future_period_refuse(tmp_path):
    for name, change, reason in (
        (
            "period",
            {"instant": date(2024, 12, 31)},
            "MAPPING_CURRENT_DEBT_COMPONENT_MISSING",
        ),
        (
            "year",
            {"namespace_uri": "http://fasb.org/us-gaap/2024"},
            "MAPPING_CURRENT_DEBT_COMPONENT_INVALID",
        ),
        (
            "future",
            {"instant": date(2026, 12, 31)},
            "MAPPING_CURRENT_DEBT_COMPONENT_MISSING",
        ),
    ):
        request, store, _ = current_debt_case(tmp_path / name, changes={0: change})
        decision = evaluate(request, store)
        assert decision.status == "abstain" and reason in decision.reason_codes


def test_segment_or_class_component_cannot_supply_issuer_total(tmp_path):
    request, store, _ = current_debt_case(
        tmp_path,
        changes={
            0: {
                "dimensions": (
                    ("us-gaap:StatementBusinessSegmentsAxis", "example:Segment"),
                ),
                "consolidation_scope": "segmented",
                "security_scope": "segmented",
            }
        },
    )
    assert (
        "MAPPING_CURRENT_DEBT_COMPONENT_MISSING"
        in evaluate(request, store).reason_codes
    )


@pytest.mark.parametrize(
    "extra",
    (
        {"value": "3600000000", "decimals": "-6"},
        {"value": "4000000000", "decimals": "-8"},
        {"namespace_uri": "http://fasb.org/us-gaap/2024"},
    ),
)
def test_duplicate_component_conflict_cannot_be_discarded(tmp_path, extra):
    request, store, _ = current_debt_case(
        tmp_path, extras=({"context_id": "duplicate", **extra},)
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None


def test_fact_order_does_not_change_selection_or_rules(tmp_path):
    from fundamental_service.current_debt_mapping import select_current_debt

    request, _, _ = current_debt_case(tmp_path)
    original = request.original
    reverse = original.model_copy(
        update={
            "report": original.report.model_copy(
                update={"facts": tuple(reversed(original.report.facts))}
            )
        }
    )
    assert select_current_debt(original) == select_current_debt(reverse)


def test_missing_totals_do_not_propose_or_infer_zero(tmp_path):
    request, _, _, _ = case(tmp_path)
    assert (
        automatic_mapping_proposal(
            ROLE,
            original=request.original,
            mapping_version=request.proposal.mapping_version,
        )
        is None
    )


def test_explicit_zero_is_observed_and_both_future_components_refuse(tmp_path):
    request, store, _ = current_debt_case(
        tmp_path / "zero", changes={1: {"value": "0"}}
    )
    decision = evaluate(request, store)
    assert decision.status == "approved"
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field=ROLE,
        mapping=decision.mapping,
    )
    assert candidates[0].value == Decimal("3542000000")
    future, store, _ = current_debt_case(
        tmp_path / "future",
        changes={i: {"instant": date(2026, 12, 31)} for i in (0, 1)},
    )
    assert "MAPPING_PERIOD_AFTER_ORIGINAL" in evaluate(future, store).reason_codes


def test_source_security_and_component_tampering_cannot_replay(tmp_path):
    request, store, roots = current_debt_case(tmp_path, security=True)
    receipt = approve(request, store, roots)
    mapping = evaluate(request, store).mapping
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    rules = mapping.accounting_rules
    forged = mapping.model_copy(
        update={
            "accounting_rules": rules.model_copy(
                update={
                    "periods": (
                        rules.periods[0].model_copy(
                            update={
                                "components": tuple(
                                    reversed(rules.periods[0].components)
                                )
                            }
                        ),
                    )
                }
            )
        }
    )
    with pytest.raises(DataReleaseError):
        verify_automatic_mapping_replay(approval, forged, artifacts=store)
    for security_id in (None, "OTHER"):
        with pytest.raises(SnapshotError):
            parsed_facts_to_candidates(
                request.original.report,
                source=security_source(request),
                issuer_id=request.original.source.cik,
                security_id=security_id,
                normalized_field=ROLE,
                mapping=mapping,
            )


def test_arithmetic_precision_limit_retains_actual_failure_reason(tmp_path):
    request, store, roots = current_debt_case(
        tmp_path,
        changes={0: {"value": "100000000000000000000000000000000", "decimals": "-2"}},
        extras=(
            {
                "context_id": "large-duplicate",
                "value": "100000000000000000000000000000000",
                "decimals": "0",
            },
        ),
    )
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "abstain" and receipt.approval_publication is None
    assert "FACT_PRECISION_UNAVAILABLE" in decision.reason_codes
    assert "MAPPING_OBSERVATION_CONFLICT" not in decision.reason_codes
