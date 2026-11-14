"""Synthetic source boundaries; real statement audits remain outside Git."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

import fundamental_service.registered_revenue as revenue
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.automatic_mapping import (
    AutomaticMappingDecisionV1,
    automatic_mapping_proposal,
    automatic_mapping_proposals,
    verify_automatic_mapping_replay,
)
from fundamental_service.automatic_mapping_batch import (
    AutomaticMappingBatchDecisionV1,
    AutomaticMappingBatchRequestV1,
)
from fundamental_service.automatic_mapping_runner import approve_mapping_batch
from fundamental_service.data_releases import (
    AutomaticMappingApprovalV1,
    verify_mapping_review_evidence,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import sha256_digest
from fundamental_service.valuation_requirements import valuation_requirements_profile
from test_automatic_mapping import MACHINE_KEY, approve, case, evaluate
from test_issuer_operating_release import inventory


def revenue_case(tmp_path, monkeypatch, *, changes=None, register=True, extra=()):
    request, store, roots, _ = case(
        tmp_path,
        observation_changes={"concept": revenue.CONTRACT_REVENUE, **(changes or {})},
        proposal_changes={"source_concept": revenue.CONTRACT_REVENUE},
        extra=extra,
    )
    original = request.original
    if register:
        scope = revenue.OriginalRevenueScope(
            original.source.parser_input_hash,
            fact_semantic_digest(original.report),
            tuple(
                (f.period_start, f.period_end)
                for f in original.report.facts
                if f.concept == revenue.CONTRACT_REVENUE
                and f.period_start is not None
                and f.period_end is not None
            ),
        )
        monkeypatch.setitem(
            revenue._ORIGINALS,
            (original.source.cik, original.source.accession_number),
            scope,
        )
    return request, store, roots


def test_contract_revenue_requires_original_scope_even_with_valid_source(
    tmp_path, monkeypatch
):
    request, store, _ = revenue_case(tmp_path, monkeypatch, register=False)
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_REVENUE_SCOPE_UNREVIEWED" in decision.reason_codes
    proposal = automatic_mapping_proposal(
        "revenue",
        mapping_version=request.proposal.mapping_version,
        original=request.original,
    )
    assert proposal.source_concept == "us-gaap:Revenues"


def test_registered_total_revenue_is_planned_signed_rebuilt_and_reused(
    tmp_path, monkeypatch
):
    request, store, roots = revenue_case(tmp_path, monkeypatch)
    proposals = automatic_mapping_proposals(
        "revenue",
        mapping_version=request.proposal.mapping_version,
        original=request.original,
        observed_only=True,
    )
    assert len(proposals) == 1
    assert proposals[0].source_concept == revenue.CONTRACT_REVENUE
    request = request.model_copy(update={"proposal": proposals[0]})
    first = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(first.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved" and not decision.reason_codes
    mapping = decision.mapping
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(first.approval_publication.artifact.artifact_id)
    )
    verify_mapping_review_evidence(approval, roots)
    assert (
        verify_automatic_mapping_replay(approval, mapping, artifacts=store) == request
    )
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field="revenue",
        mapping=mapping,
    )
    selected = revenue.select_registered_revenue(request.original).selected
    assert candidates
    assert {c.value for c in candidates} == {Decimal(f.value) for f in selected}
    assert all(not c.dimensions for c in candidates)
    before = inventory(store.root)
    repeated = approve(request, ArtifactStore(store.root), roots)
    assert inventory(store.root) == before
    assert repeated.output_digest == first.output_digest
    assert all(
        not publication.wrote
        for publication in (
            repeated.input_publication,
            repeated.decision_publication,
            repeated.approval_publication,
        )
    )


@pytest.mark.parametrize("field", ("parser_input_hash", "fact_digest"))
def test_changed_original_cannot_reuse_a_total_revenue_classification(
    tmp_path, monkeypatch, field
):
    request, store, _ = revenue_case(tmp_path, monkeypatch)
    key = request.original.source.cik, request.original.source.accession_number
    monkeypatch.setitem(
        revenue._ORIGINALS,
        key,
        replace(revenue._ORIGINALS[key], **{field: "b" * 64}),
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_REVENUE_SOURCE_MISMATCH" in decision.reason_codes


def test_registration_does_not_authorize_another_annual_period(tmp_path, monkeypatch):
    request, store, _ = revenue_case(tmp_path, monkeypatch)
    key = request.original.source.cik, request.original.source.accession_number
    monkeypatch.setitem(
        revenue._ORIGINALS,
        key,
        replace(
            revenue._ORIGINALS[key],
            annual_periods=((date(2000, 1, 1), date(2000, 12, 31)),),
        ),
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_NO_ELIGIBLE_OBSERVATIONS" in decision.reason_codes
    assert {rejected.reason_code for rejected in decision.rejected_observations} == {
        "MAPPING_REVENUE_PERIOD_SCOPE_UNREVIEWED"
    }


@pytest.mark.parametrize(
    "changes, reason",
    (
        (
            {"namespace_uri": "https://example.com/us-gaap/2026"},
            "MAPPING_NAMESPACE_UNSUPPORTED",
        ),
        ({"entity_identifier": "9999999999"}, "MAPPING_ISSUER_MISMATCH"),
        ({"value": "NaN"}, "MAPPING_VALUE_INVALID"),
        ({"decimals": None}, "MAPPING_PRECISION_UNAVAILABLE"),
        ({"period_start": date(2023, 10, 1)}, "MAPPING_PERIOD_UNSUPPORTED"),
        ({"security_scope": "segmented"}, "MAPPING_SCOPE_UNSUPPORTED"),
    ),
)
def test_registered_source_still_requires_valid_annual_base_context(
    tmp_path, monkeypatch, changes, reason
):
    request, store, _ = revenue_case(tmp_path, monkeypatch, changes=changes)
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert reason in {r.reason_code for r in decision.rejected_observations}
    assert "MAPPING_NO_ELIGIBLE_OBSERVATIONS" in decision.reason_codes


def test_foreign_currency_refuses_at_original_boundary(tmp_path, monkeypatch):
    request, store, _ = revenue_case(
        tmp_path, monkeypatch, changes={"unit": "iso4217:EUR"}
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "ORIGINAL_ISSUER_CURRENCY_UNSUPPORTED" in decision.reason_codes


def test_conflicting_statement_totals_refuse_even_in_registered_scope(
    tmp_path, monkeypatch
):
    seed, _, _ = revenue_case(tmp_path / "seed", monkeypatch)
    fact = next(
        f for f in seed.original.report.facts if f.concept == revenue.CONTRACT_REVENUE
    )
    conflict = fact.model_copy(
        update={"context_id": "conflict", "value": str(Decimal(fact.value) + 1)}
    )
    request, store, _ = revenue_case(
        tmp_path / "conflict", monkeypatch, extra=(conflict,)
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_OBSERVATION_CONFLICT" in decision.reason_codes


def test_automatic_batch_consumes_the_original_bound_revenue_proposal(
    tmp_path, monkeypatch
):
    request, store, roots = revenue_case(tmp_path, monkeypatch)
    batch = AutomaticMappingBatchRequestV1(
        **request.model_dump(exclude={"protocol", "proposal"}),
        mapping_version=request.proposal.mapping_version,
        model_version="fcff_dcf-v2",
        requirements=valuation_requirements_profile("fcff_dcf"),
    )
    first = approve_mapping_batch(
        batch, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    decision = AutomaticMappingBatchDecisionV1.model_validate_json(
        store.read(first.decision_publication.artifact.artifact_id)
    )
    role = next(r for r in decision.roles if r.normalized_field == "revenue")
    assert role.status == "approved" and not role.reason_codes
    mapping = AutomaticMappingDecisionV1.model_validate_json(
        store.read(role.decision.artifact_id)
    ).mapping
    assert mapping.source_concept == revenue.CONTRACT_REVENUE
    before = inventory(store.root)
    repeated = approve_mapping_batch(
        batch, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    assert not repeated.wrote and repeated.output_digest == first.output_digest
    assert inventory(store.root) == before


def test_total_revenue_mapping_retains_exact_report_observations(tmp_path, monkeypatch):
    request, store, _ = revenue_case(tmp_path, monkeypatch)
    decision = evaluate(request, store)
    assert decision.status == "approved"
    assert decision.mapping.observation_scope.observation_digests == tuple(
        sorted(
            sha256_digest(f)
            for f in request.original.report.facts
            if f.concept == revenue.CONTRACT_REVENUE
        )
    )
