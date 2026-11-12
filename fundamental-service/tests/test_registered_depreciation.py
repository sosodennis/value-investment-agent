"""Registered scope, real arithmetic and authenticated repeat using synthetic sources."""

from datetime import date
from decimal import Decimal

import pytest

from fundamental_service import registered_depreciation as policy
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.automatic_mapping import (
    AutomaticMappingApprovalV1,
    AutomaticMappingDecisionV1,
    verify_automatic_mapping_replay,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import sha256_digest
from test_automatic_mapping import approve, case, evaluate
from test_issuer_operating_release import inventory


def depreciation_case(tmp_path, monkeypatch, *, adjusted=True):
    request, _, _, _ = case(tmp_path / "template")
    template = next(
        f for f in request.original.report.facts if f.concept == "us-gaap:Revenues"
    )
    total = template.model_copy(
        update={
            "concept": policy.DEPRECIATION,
            "value": "46144000",
            "decimals": "-3",
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 12, 31),
        }
    )
    excluded = total.model_copy(
        update={
            "context_id": "discontinued",
            "value": "5000000",
            "decimals": "-6",
            "dimensions": (
                (
                    "us-gaap:IncomeStatementLocationAxis",
                    "neu:IncomeLossFromOperationsOfDiscontinuedBusinessNetOfTaxMember",
                ),
                (
                    "us-gaap:StatementBusinessSegmentsAxis",
                    "us-gaap:AllOtherSegmentsMember",
                ),
            ),
            "consolidation_scope": "segmented",
            "security_scope": "segmented",
        }
    )
    prior = total.model_copy(
        update={
            "context_id": "continuing-prior",
            "value": "41538000",
            "period_start": date(2024, 1, 1),
            "period_end": date(2024, 12, 31),
        }
    )
    note = template.model_copy(
        update={
            "concept": "us-gaap:SegmentReportingDisclosureTextBlock",
            "context_id": "classification",
            "is_numeric": False,
            "unit": None,
            "value": "The amount for 2025 includes depreciation and amortization in income of discontinued business in the Consolidated Statements of Income.",
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 12, 31),
        }
    )
    request, store, roots, bundle = case(
        tmp_path / "actual",
        extra=(total, excluded, prior, note),
        proposal_changes={
            "source_concept": policy.ADJUSTED_DEPRECIATION
            if adjusted
            else policy.DEPRECIATION,
            "normalized_field": "depreciation_and_amortization",
        },
    )
    original = request.original
    monkeypatch.setattr(
        policy,
        "_ORIGINALS",
        {
            (
                original.source.cik,
                original.source.accession_number,
            ): policy.OriginalClassification(
                original.source.content_hash,
                fact_semantic_digest(original.report),
                (2024,),
                (2025,),
            )
        },
    )
    return request, store, roots, bundle


def test_rounded_exclusion_is_signed_reproduced_and_reused(tmp_path, monkeypatch):
    request, store, roots, _ = depreciation_case(tmp_path, monkeypatch)
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved"
    mapping = decision.mapping
    assert mapping.accounting_rules is not None and mapping.observation_scope is None
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field="depreciation_and_amortization",
        mapping=mapping,
    )
    assert len(candidates) == 1
    assert candidates[0].value == Decimal("41144000") and candidates[0].decimals == -6
    before = inventory(store.root)
    repeated = approve(request, store, roots)
    assert repeated.input_digest == receipt.input_digest
    assert repeated.output_digest == receipt.output_digest
    assert not repeated.input_publication.wrote
    assert not repeated.decision_publication.wrote
    assert not repeated.approval_publication.wrote
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    assert (
        verify_automatic_mapping_replay(
            approval, mapping, artifacts=ArtifactStore(store.root)
        )
        == request
    )
    assert inventory(store.root) == before


def test_unadjusted_total_cannot_include_a_registered_discontinued_year(
    tmp_path, monkeypatch
):
    request, store, _, _ = depreciation_case(tmp_path, monkeypatch, adjusted=False)
    decision = evaluate(request, store)
    assert decision.status == "approved"
    assert len(decision.mapping.observation_scope.observation_digests) == 1
    assert (
        decision.rejected_observations[0].reason_code
        == "MAPPING_DA_DISCONTINUED_ADJUSTMENT_REQUIRED"
    )
    facts = {sha256_digest(f): f for f in request.original.report.facts}
    assert {
        facts[k].period_end.year for k in decision.eligible_observation_digests
    } == {2024}


@pytest.mark.parametrize(
    "change",
    ("issuer", "accession", "source", "amount", "precision", "passage", "dimension"),
)
def test_registry_does_not_authorize_changed_sources(tmp_path, monkeypatch, change):
    request, store, _, _ = depreciation_case(tmp_path, monkeypatch)
    original = request.original
    if change in {"issuer", "accession", "source"}:
        field, value = {
            "issuer": ("cik", "0000000002"),
            "accession": ("accession_number", "0000000002-26-000001"),
            "source": ("content_hash", "f" * 64),
        }[change]
        original = original.model_copy(
            update={"source": original.source.model_copy(update={field: value})}
        )
    else:
        facts = list(original.report.facts)
        i = next(i for i, f in enumerate(facts) if f.concept == policy.DEPRECIATION)
        update = {
            "amount": {"value": "46144001"},
            "precision": {"decimals": "0"},
            "dimension": {"dimensions": (("example:Axis", "example:Member"),)},
        }
        if change == "passage":
            i = next(
                i
                for i, f in enumerate(facts)
                if f.concept == "us-gaap:SegmentReportingDisclosureTextBlock"
            )
            facts[i] = facts[i].model_copy(
                update={"value": "Unresolved source classification."}
            )
        else:
            facts[i] = facts[i].model_copy(update=update[change])
        original = original.model_copy(
            update={
                "report": original.report.model_copy(update={"facts": tuple(facts)})
            }
        )
    result = evaluate(request.model_copy(update={"original": original}), store)
    assert result.status == "abstain" and result.mapping is None
    assert set(result.reason_codes) & {
        "MAPPING_DA_SCOPE_UNREVIEWED",
        "MAPPING_DA_SOURCE_MISMATCH",
    }


def test_production_registry_rejects_an_unregistered_issuer(tmp_path):
    request, store, _, _ = case(
        tmp_path,
        proposal_changes={
            "normalized_field": "depreciation_and_amortization",
            "source_concept": policy.DEPRECIATION,
        },
    )
    result = evaluate(request, store)
    assert (
        result.status == "abstain"
        and "MAPPING_DA_SCOPE_UNREVIEWED" in result.reason_codes
    )
