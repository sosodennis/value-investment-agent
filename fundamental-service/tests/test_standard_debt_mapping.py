"""Standard noncurrent debt mapping, distinct from current debt and leases."""

from datetime import date
from decimal import Decimal

import pytest

from fundamental_service.automatic_mapping import (
    AutomaticMappingDecisionV1,
    automatic_mapping_proposal,
    verify_automatic_mapping_replay,
)
from fundamental_service.data_releases import AutomaticMappingApprovalV1
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from test_automatic_mapping import approve, case, evaluate
from test_issuer_operating_release import inventory

ROLE = "long_term_interest_bearing_debt"
CONCEPT = "us-gaap:LongTermDebtNoncurrent"


def debt_case(tmp_path, *, change=None, duplicate_value=None):
    template, _, _, _ = case(tmp_path / "template")
    base = next(f for f in template.original.report.facts if f.is_numeric)
    debt = base.model_copy(
        update={
            "concept": CONCEPT,
            "context_id": "noncurrent-debt",
            "instant": date(2025, 12, 31),
            "period_start": None,
            "period_end": None,
            "value": "31067000000",
            "decimals": "-6",
            "namespace_uri": "http://fasb.org/us-gaap/2025",
            **(change or {}),
        }
    )
    extra = (debt,)
    if duplicate_value is not None:
        extra += (
            debt.model_copy(
                update={"context_id": "duplicate", "value": duplicate_value}
            ),
        )
    return case(
        tmp_path / "actual",
        extra=extra,
        proposal_changes={"source_concept": CONCEPT, "normalized_field": ROLE},
    )


@pytest.mark.parametrize("year", (2024, 2025))
def test_standard_noncurrent_debt_rebuilds_and_replays_without_new_writes(
    tmp_path, year
):
    request, store, roots, _ = debt_case(
        tmp_path, change={"namespace_uri": f"http://fasb.org/us-gaap/{year}"}
    )
    proposal = automatic_mapping_proposal(
        ROLE,
        original=request.original,
        mapping_version=request.proposal.mapping_version,
    )
    assert proposal is not None and proposal.source_concept == CONCEPT
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved"
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field=ROLE,
        mapping=decision.mapping,
    )
    assert len(candidates) == 1
    assert candidates[0].value == Decimal("31067000000")
    assert candidates[0].decimals == -6
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    assert (
        verify_automatic_mapping_replay(approval, decision.mapping, artifacts=store)
        == request
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
    "change,reason",
    (
        (
            {"namespace_uri": "http://fasb.org/us-gaap/2023"},
            "MAPPING_NAMESPACE_UNSUPPORTED",
        ),
        (
            {"namespace_uri": "https://example.test/us-gaap/2025"},
            "MAPPING_NAMESPACE_UNSUPPORTED",
        ),
        ({"value": "-1"}, "MAPPING_VALUE_INVALID"),
        ({"decimals": None}, "MAPPING_PRECISION_UNAVAILABLE"),
        ({"entity_identifier": "999999"}, "MAPPING_ISSUER_MISMATCH"),
        ({"instant": date(2026, 12, 31)}, "MAPPING_PERIOD_AFTER_ORIGINAL"),
        ({"unit": "xbrli:shares"}, "MAPPING_UNIT_UNSUPPORTED"),
    ),
)
def test_invalid_noncurrent_observation_retains_reason(tmp_path, change, reason):
    request, store, _, _ = debt_case(tmp_path, change=change)
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert reason in {r.reason_code for r in decision.rejected_observations}


def test_conflicting_noncurrent_balances_refuse(tmp_path):
    request, store, _, _ = debt_case(tmp_path, duplicate_value="32000000000")
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert "MAPPING_OBSERVATION_CONFLICT" in decision.reason_codes


def test_equivalent_balances_preserve_distinct_source_contexts(tmp_path):
    request, store, _, _ = debt_case(tmp_path, duplicate_value="31067000000")
    decision = evaluate(request, store)
    assert decision.status == "approved"
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field=ROLE,
        mapping=decision.mapping,
    )
    assert len({c.candidate_id for c in candidates}) == 2
    assert {c.value for c in candidates} == {Decimal("31067000000")}
    assert {c.decimals for c in candidates} == {-6}


def test_residual_proposal_cannot_override_reported_noncurrent_debt(tmp_path):
    from fundamental_service.registered_liability_residuals import (
        NONCURRENT_LIABILITY_RESIDUAL,
    )

    request, store, _, _ = debt_case(tmp_path)
    request = request.model_copy(
        update={
            "proposal": request.proposal.model_copy(
                update={"source_concept": NONCURRENT_LIABILITY_RESIDUAL}
            )
        }
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert "MAPPING_DEBT_DIRECT_REPRESENTATION_REQUIRED" in decision.reason_codes


@pytest.mark.parametrize(
    "concept",
    ("us-gaap:LongTermDebtCurrent", "us-gaap:LongTermDebt", "us-gaap:DebtCurrent"),
)
def test_current_total_and_lease_inclusive_tags_cannot_supply_noncurrent_debt(
    tmp_path, concept
):
    request, store, _, _ = debt_case(tmp_path, change={"concept": concept})
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert "MAPPING_NO_ELIGIBLE_OBSERVATIONS" in decision.reason_codes


def test_missing_noncurrent_balance_does_not_infer_zero_or_current_debt(tmp_path):
    request, _, _, _ = case(tmp_path)
    for role in (ROLE, "current_interest_bearing_debt"):
        assert (
            automatic_mapping_proposal(
                role,
                original=request.original,
                mapping_version=request.proposal.mapping_version,
            )
            is None
        )
