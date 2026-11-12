"""Registered scope, real arithmetic and authenticated repeat using synthetic sources."""

from datetime import date
from decimal import Decimal

import pytest

from fundamental_service import registered_depreciation as policy
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.automatic_mapping import (
    AutomaticMappingApprovalV1,
    AutomaticMappingDecisionV1,
    automatic_mapping_proposal,
    verify_automatic_mapping_replay,
)
from fundamental_service.automatic_mapping_batch import AutomaticMappingBatchRequestV1
from fundamental_service.automatic_mapping_runner import approve_mapping_batch
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import sha256_digest
from fundamental_service.valuation_requirements import valuation_requirements_profile
from test_automatic_mapping import approve, case, evaluate, MACHINE_KEY
from test_automatic_mapping_batch import read_decision
from test_issuer_operating_release import inventory


def operating_depreciation_case(tmp_path, monkeypatch):
    template, _, _, _ = case(tmp_path / "template")
    base = next(
        f for f in template.original.report.facts if f.concept == "us-gaap:Revenues"
    )
    facts = tuple(
        base.model_copy(
            update={
                "concept": concept,
                "context_id": f"operating-{year}",
                "value": value,
                "period_start": date(year, 1, 1),
                "period_end": date(year, 12, 31),
            }
        )
        for year, concept, value in (
            (2024, policy.DEPRECIATION, "257606"),
            (2024, policy.FIXED_ASSET_DEPRECIATION, "196738"),
            (2025, policy.DEPRECIATION, "308147"),
            (2025, policy.FIXED_ASSET_DEPRECIATION, "308147"),
        )
    )
    request, store, roots, bundle = case(
        tmp_path / "actual",
        extra=facts,
        proposal_changes={
            "source_concept": policy.DEPRECIATION,
            "normalized_field": "depreciation_and_amortization",
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
                (2024, 2025),
                (),
                policy.FIXED_ASSET_DEPRECIATION,
            )
        },
    )
    return request, store, roots, bundle


def test_bound_operating_concept_excludes_the_cash_flow_aggregate(
    tmp_path, monkeypatch
):
    request, store, roots, _ = operating_depreciation_case(tmp_path, monkeypatch)
    proposal = automatic_mapping_proposal(
        "depreciation_and_amortization",
        mapping_version=request.proposal.mapping_version,
        original=request.original,
    )
    assert proposal.source_concept == policy.FIXED_ASSET_DEPRECIATION
    request = request.model_copy(update={"proposal": proposal})
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved"
    assert len(decision.rejected_observations) == 2
    assert {r.reason_code for r in decision.rejected_observations} == {
        "MAPPING_DA_DIFFERENT_ACCOUNTING_SCOPE"
    }
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field="depreciation_and_amortization",
        mapping=decision.mapping,
    )
    assert {f.period_end.year: f.value for f in candidates} == {
        2024: Decimal("196738"),
        2025: Decimal("308147"),
    }
    before = inventory(store.root)
    repeat = approve(request, store, roots)
    assert (repeat.input_digest, repeat.output_digest) == (
        receipt.input_digest,
        receipt.output_digest,
    )
    assert not any(
        p.wrote
        for p in (
            repeat.input_publication,
            repeat.decision_publication,
            repeat.approval_publication,
        )
    )
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    assert (
        verify_automatic_mapping_replay(
            approval, decision.mapping, artifacts=ArtifactStore(store.root)
        )
        == request
    )
    assert inventory(store.root) == before


def test_bound_operating_scope_refuses_aggregate_even_when_one_period_agrees(
    tmp_path, monkeypatch
):
    request, store, _, _ = operating_depreciation_case(tmp_path, monkeypatch)
    result = evaluate(request, store)
    assert result.status == "abstain" and result.mapping is None
    assert "MAPPING_DA_CONCEPT_SCOPE_UNREVIEWED" in result.reason_codes
    assert len(result.rejected_observations) == 2


def test_batch_uses_the_original_bound_concept_and_keeps_other_missing_roles(
    tmp_path, monkeypatch
):
    request, store, roots, _ = operating_depreciation_case(tmp_path, monkeypatch)
    batch = AutomaticMappingBatchRequestV1(
        **request.model_dump(exclude={"protocol", "proposal"}),
        mapping_version=request.proposal.mapping_version,
        model_version="fcff_dcf-v2",
        requirements=valuation_requirements_profile("fcff_dcf"),
    )
    receipt = approve_mapping_batch(
        batch, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    roles = {r.normalized_field: r for r in read_decision(receipt, store).roles}
    assert roles["depreciation_and_amortization"].status == "approved"
    child = AutomaticMappingDecisionV1.model_validate_json(
        store.read(roles["depreciation_and_amortization"].decision.artifact_id)
    )
    assert child.mapping.source_concept == policy.FIXED_ASSET_DEPRECIATION
    assert roles["non_operating_assets"].status == "abstain"
    assert roles["non_operating_assets"].approval is None
    assert batch.requirements.supported_history_threshold is None


@pytest.mark.parametrize("change", ("source", "amount", "period", "precision"))
def test_operating_proposal_does_not_inherit_a_changed_original(
    tmp_path, monkeypatch, change
):
    request, store, _, _ = operating_depreciation_case(tmp_path, monkeypatch)
    original = request.original
    if change == "source":
        original = original.model_copy(
            update={
                "source": original.source.model_copy(update={"content_hash": "f" * 64})
            }
        )
    else:
        facts = list(original.report.facts)
        index = next(
            i
            for i, f in enumerate(facts)
            if f.concept == policy.FIXED_ASSET_DEPRECIATION
        )
        facts[index] = facts[index].model_copy(
            update={
                "amount": {"value": "196739"},
                "period": {"period_end": date(2023, 12, 31)},
                "precision": {"decimals": "-6"},
            }[change]
        )
        original = original.model_copy(
            update={
                "report": original.report.model_copy(update={"facts": tuple(facts)})
            }
        )
    proposal = automatic_mapping_proposal(
        "depreciation_and_amortization",
        mapping_version=request.proposal.mapping_version,
        original=original,
    )
    assert proposal.source_concept == policy.DEPRECIATION
    result = evaluate(
        request.model_copy(update={"original": original, "proposal": proposal}), store
    )
    assert result.status == "abstain" and result.mapping is None


def test_operating_scope_and_rejections_do_not_depend_on_fact_order(
    tmp_path, monkeypatch
):
    request, store, _, _ = operating_depreciation_case(tmp_path, monkeypatch)
    proposal = automatic_mapping_proposal(
        "depreciation_and_amortization",
        mapping_version=request.proposal.mapping_version,
        original=request.original,
    )
    request = request.model_copy(update={"proposal": proposal})
    first = evaluate(request, store)
    original = request.original.model_copy(
        update={
            "report": request.original.report.model_copy(
                update={"facts": tuple(reversed(request.original.report.facts))}
            )
        }
    )
    second = evaluate(request.model_copy(update={"original": original}), store)
    assert first.status == second.status == "approved"
    assert first.mapping == second.mapping
    assert first.rejected_observations == second.rejected_observations
    assert first.eligible_observation_digests == second.eligible_observation_digests


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
