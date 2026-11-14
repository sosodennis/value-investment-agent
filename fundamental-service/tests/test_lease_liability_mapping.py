"""Synthetic boundary tests; real filing acceptance is recorded separately."""

from datetime import date
from decimal import Decimal, Inexact, localcontext

import pytest

from fundamental_service.accounting_roles import evaluate_period_rule
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.automatic_mapping import (
    AutomaticMappingDecisionV1,
    automatic_mapping_proposal,
    automatic_mapping_proposals,
    verify_automatic_mapping_replay,
)
from fundamental_service.data_releases import ArtifactRefV1, AutomaticMappingApprovalV1
from fundamental_service.lease_liability_mapping import select_lease_liability
from fundamental_service.original_issuer import evaluate_original_issuer
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_automatic_mapping import approve, case, evaluate
from test_issuer_operating_release import inventory


def lease_case(
    tmp_path,
    *,
    kind="finance",
    noncurrent=False,
    change=None,
    extra=(),
    omit_total=False,
):
    request, store, roots, _ = case(tmp_path)
    concept = (
        "us-gaap:"
        + ("Finance" if kind == "finance" else "Operating")
        + "LeaseLiability"
    )
    role = ("long_term_" if noncurrent else "current_") + kind + "_lease_liabilities"
    base = next(
        f
        for f in request.original.report.facts
        if f.instant is not None and f.is_numeric and f.unit == "iso4217:USD"
    )
    total = base.model_copy(
        update={"concept": concept, "value": "100", "decimals": "0"}
    )
    current = total.model_copy(
        update={
            "value": "20",
            "context_id": "classified-current",
            "dimensions": (
                (
                    "us-gaap:BalanceSheetLocationAxis",
                    "us-gaap:OtherCurrentLiabilitiesMember",
                ),
            ),
            "consolidation_scope": "segmented",
            "security_scope": "segmented",
            **(change or {}),
        }
    )
    report = request.original.report.model_copy(
        update={
            "facts": (
                *request.original.report.facts,
                *(() if omit_total else (total,)),
                current,
                *extra,
            ),
        }
    )
    original = evaluate_original_issuer(
        report, source=request.original.source, decision_at=request.original.decision_at
    )
    integrity = request.integrity.model_copy(
        update={
            "normalized_fact_count": len(report.facts),
            "archive_fact_count": len(report.facts),
            "normalized_fact_digest": fact_semantic_digest(report),
            "archive_fact_digest": fact_semantic_digest(report),
        }
    )
    publication = store.put_bytes_with_receipt(
        "lease-integrity-" + sha256_digest(integrity), canonical_bytes(integrity)
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
        role, mapping_version=request.proposal.mapping_version, original=original
    )
    return (
        request.model_copy(
            update={
                "original": original,
                "integrity": integrity,
                "evidence_refs": refs,
                "proposal": proposal or request.proposal,
            }
        ),
        store,
        roots,
        role,
        total,
        current,
    )


@pytest.mark.parametrize("kind", ["finance", "operating"])
@pytest.mark.parametrize(
    "noncurrent,expected", [(False, Decimal("20")), (True, Decimal("80"))]
)
def test_classified_lease_approval_rebuilds_and_replays_without_scope_loss(
    tmp_path, kind, noncurrent, expected
):
    request, store, roots, role, _, current = lease_case(
        tmp_path, kind=kind, noncurrent=noncurrent
    )
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved", decision.reason_codes
    mapping = decision.mapping
    assert mapping is not None and mapping.accounting_rules is not None
    assert mapping.observation_scope is None
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field=role,
        mapping=mapping,
    )
    assert len(candidates) == 1 and candidates[0].value == expected
    assert current in candidates[0].accounting_evidence.source_facts
    assert candidates[0].dimensions == ()
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    assert (
        verify_automatic_mapping_replay(approval, mapping, artifacts=store) == request
    )
    before = inventory(store.root)
    repeated = approve(request, ArtifactStore(store.root), roots)
    assert repeated.output_digest == receipt.output_digest
    assert repeated.decision_publication.wrote is False
    assert repeated.approval_publication.wrote is False
    assert inventory(store.root) == before


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"entity_identifier": "99999"}, "MAPPING_LEASE_COMPONENT_INVALID"),
        ({"entity_scheme": "urn:other"}, "MAPPING_LEASE_COMPONENT_INVALID"),
        (
            {"namespace_uri": "https://example.test/us-gaap/2026"},
            "MAPPING_LEASE_COMPONENT_INVALID",
        ),
        ({"unit": "iso4217:EUR"}, "MAPPING_LEASE_COMPONENT_INVALID"),
        ({"decimals": None}, "MAPPING_LEASE_COMPONENT_INVALID"),
        ({"value": "NaN"}, "MAPPING_LEASE_COMPONENT_INVALID"),
        ({"value": "-1"}, "MAPPING_LEASE_COMPONENT_INVALID"),
        ({"is_numeric": False}, "MAPPING_LEASE_COMPONENT_INVALID"),
        ({"consolidation_scope": "consolidated"}, "MAPPING_LEASE_COMPONENT_INVALID"),
        ({"security_scope": "security"}, "MAPPING_LEASE_COMPONENT_INVALID"),
        ({"instant": date(2099, 12, 31)}, "MAPPING_PERIOD_AFTER_ORIGINAL"),
        ({"period_start": date(2023, 1, 1)}, "MAPPING_LEASE_COMPONENT_INVALID"),
    ],
)
def test_invalid_classified_observation_abstains_without_an_approved_mapping(
    tmp_path, change, reason
):
    request, store, _, _, _, _ = lease_case(tmp_path, change=change)
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert reason in decision.reason_codes


@pytest.mark.parametrize("noncurrent", [False, True])
def test_conflicting_duplicate_current_observation_abstains(tmp_path, noncurrent):
    _, _, _, _, _, current = lease_case(tmp_path / "base")
    request, store, _, _, _, _ = lease_case(
        tmp_path / "conflict",
        noncurrent=noncurrent,
        extra=(current.model_copy(update={"value": "21"}),),
    )
    assert "MAPPING_OBSERVATION_CONFLICT" in evaluate(request, store).reason_codes


def test_total_is_required_for_noncurrent_and_missing_is_not_zero(tmp_path):
    request, store, _, _, _, _ = lease_case(tmp_path, noncurrent=True, omit_total=True)
    assert "MAPPING_LEASE_COMPONENT_MISSING" in evaluate(request, store).reason_codes


@pytest.mark.parametrize("noncurrent", [False, True])
def test_current_portion_cannot_exceed_total(tmp_path, noncurrent):
    request, store, _, _, _, _ = lease_case(
        tmp_path, noncurrent=noncurrent, change={"value": "101"}
    )
    assert "MAPPING_LEASE_RESIDUAL_INVALID" in evaluate(request, store).reason_codes


@pytest.mark.parametrize(
    "changes",
    [
        {"value": "99"},
        {"namespace_uri": "http://fasb.org/us-gaap/2020"},
        {"unit": "iso4217:EUR"},
        {"decimals": None},
    ],
)
def test_conflicting_or_invalid_totals_abstain(tmp_path, changes):
    _, _, _, _, total, _ = lease_case(tmp_path / "base")
    request, store, _, _, _, _ = lease_case(
        tmp_path / "invalid", noncurrent=True, extra=(total.model_copy(update=changes),)
    )
    assert evaluate(request, store).status == "abstain"


def test_equivalent_duplicates_and_fact_order_preserve_mapping(tmp_path):
    request, store, _, role, _, current = lease_case(tmp_path / "base", noncurrent=True)
    with_duplicate, duplicate_store, _, _, _, _ = lease_case(
        tmp_path / "duplicate",
        noncurrent=True,
        extra=(current.model_copy(update={"context_id": "duplicate"}),),
    )
    assert (
        evaluate(request, store).status
        == evaluate(with_duplicate, duplicate_store).status
        == "approved"
    )
    original = with_duplicate.original
    reversed_original = original.model_copy(
        update={
            "report": original.report.model_copy(
                update={"facts": tuple(reversed(original.report.facts))}
            )
        }
    )
    assert select_lease_liability(original, role) == select_lease_liability(
        reversed_original, role
    )


@pytest.mark.parametrize("kind", ["finance", "operating"])
@pytest.mark.parametrize("noncurrent", [False, True])
@pytest.mark.parametrize("conflict", [False, True])
def test_direct_representation_must_agree_with_classification(
    tmp_path, kind, noncurrent, conflict
):
    _, _, _, _, total, _ = lease_case(tmp_path / "base", kind=kind)
    direct = total.model_copy(
        update={
            "concept": total.concept + ("Noncurrent" if noncurrent else "Current"),
            "value": "99" if conflict else ("80" if noncurrent else "20"),
        }
    )
    request, store, _, _, _, _ = lease_case(
        tmp_path / "comparison", kind=kind, noncurrent=noncurrent, extra=(direct,)
    )
    decision = evaluate(request, store)
    assert decision.status == ("abstain" if conflict else "approved"), (
        decision.reason_codes
    )
    if conflict:
        assert "MAPPING_OBSERVATION_CONFLICT" in decision.reason_codes


@pytest.mark.parametrize("noncurrent", [False, True])
def test_direct_proposal_cannot_bypass_conflicting_current_location(
    tmp_path, noncurrent
):
    _, _, _, _, total, _ = lease_case(tmp_path / "base", kind="operating")
    direct = total.model_copy(
        update={
            "concept": total.concept + ("Noncurrent" if noncurrent else "Current"),
            "value": "99",
        }
    )
    request, store, _, _, _, _ = lease_case(
        tmp_path / "conflict", kind="operating", noncurrent=noncurrent, extra=(direct,)
    )
    request = request.model_copy(
        update={
            "proposal": request.proposal.model_copy(
                update={"source_concept": direct.concept}
            )
        }
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_OBSERVATION_CONFLICT" in decision.reason_codes


def test_arbitrary_segment_is_not_reclassified_as_current(tmp_path):
    request, _, _, role, _, _ = lease_case(
        tmp_path,
        change={
            "dimensions": (
                ("us-gaap:StatementBusinessSegmentsAxis", "issuer:CloudMember"),
            )
        },
    )
    selection = select_lease_liability(request.original, role)
    assert selection.rules is None and not selection.selected
    assert selection.reason_codes == ("MAPPING_LEASE_SCOPE_UNSUPPORTED",)


@pytest.mark.parametrize("kind", ["finance", "operating"])
@pytest.mark.parametrize("conflict", [False, True])
def test_standard_noncurrent_location_must_agree_with_derived_residual(
    tmp_path, kind, conflict
):
    _, _, _, _, total, _ = lease_case(tmp_path / "base", kind=kind)
    noncurrent = total.model_copy(
        update={
            "value": "79" if conflict else "80",
            "dimensions": (
                (
                    "us-gaap:BalanceSheetLocationAxis",
                    "us-gaap:OtherNoncurrentLiabilitiesMember",
                ),
            ),
            "consolidation_scope": "segmented",
            "security_scope": "segmented",
        }
    )
    request, store, _, _, _, _ = lease_case(
        tmp_path / "comparison", kind=kind, noncurrent=True, extra=(noncurrent,)
    )
    decision = evaluate(request, store)
    assert decision.status == ("abstain" if conflict else "approved")
    if conflict:
        assert "MAPPING_OBSERVATION_CONFLICT" in decision.reason_codes


@pytest.mark.parametrize("noncurrent", [False, True])
def test_historical_classification_retains_newer_supported_direct_observation(
    tmp_path, noncurrent
):
    _, _, _, _, total, _ = lease_case(tmp_path / "base", kind="operating")
    historical = total.instant.replace(year=total.instant.year - 1)
    direct = total.model_copy(
        update={
            "concept": total.concept + ("Noncurrent" if noncurrent else "Current"),
            "value": "33",
        }
    )
    request, store, _, role, _, _ = lease_case(
        tmp_path / "mixed",
        kind="operating",
        noncurrent=noncurrent,
        change={"instant": historical},
        extra=(total.model_copy(update={"instant": historical}), direct),
    )
    proposals = automatic_mapping_proposals(
        role,
        mapping_version=request.proposal.mapping_version,
        original=request.original,
    )
    assert len(proposals) == 2
    values = {}
    for proposal in proposals:
        decision = evaluate(request.model_copy(update={"proposal": proposal}), store)
        assert decision.status == "approved", decision.reason_codes
        for candidate in parsed_facts_to_candidates(
            request.original.report,
            source=request.original.source,
            issuer_id=request.original.source.cik,
            normalized_field=role,
            mapping=decision.mapping,
        ):
            assert candidate.instant not in values
            values[candidate.instant] = candidate.value
    assert values == {
        historical: Decimal("80" if noncurrent else "20"),
        total.instant: Decimal("33"),
    }


def test_component_evaluation_uses_formal_decimal_context_and_security_binding(
    tmp_path,
):
    request, _, _, role, _, _ = lease_case(tmp_path, noncurrent=True)
    selection = select_lease_liability(request.original, role, security_id="SYNTH")
    assert selection.rules.security_id == "SYNTH"
    with localcontext() as context:
        context.prec = 1
        context.traps[Inexact] = True
        assert evaluate_period_rule(
            selection.rules, selection.rules.periods[0], selection.selected
        ) == Decimal("80")
