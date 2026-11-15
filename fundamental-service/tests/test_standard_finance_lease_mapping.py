"""Only disclosed discounted current/noncurrent finance-lease balances qualify."""

from datetime import date
from decimal import Decimal

import pytest

from fundamental_service.automatic_mapping import automatic_mapping_proposal
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from test_automatic_mapping import case, evaluate
from test_standard_debt_mapping import debt_case

PAIRS = (
    ("current_finance_lease_liabilities", "us-gaap:FinanceLeaseLiabilityCurrent"),
    ("long_term_finance_lease_liabilities", "us-gaap:FinanceLeaseLiabilityNoncurrent"),
)


def finance_case(tmp_path, role, concept, *, change=None, duplicate_value=None):
    request, store, roots, bundle = debt_case(
        tmp_path,
        change={"concept": concept, **(change or {})},
        duplicate_value=duplicate_value,
    )
    request = request.model_copy(
        update={
            "proposal": request.proposal.model_copy(
                update={"normalized_field": role, "source_concept": concept}
            )
        }
    )
    return request, store, roots, bundle


@pytest.mark.parametrize("role,concept", PAIRS)
@pytest.mark.parametrize("year", (2023, 2024, 2025, 2026))
def test_standard_discounted_balance_is_reusable_without_issuer_registration(
    tmp_path, role, concept, year
):
    request, store, _, _ = finance_case(
        tmp_path,
        role,
        concept,
        change={"namespace_uri": f"http://fasb.org/us-gaap/{year}"},
    )
    proposal = automatic_mapping_proposal(
        role,
        original=request.original,
        mapping_version=request.proposal.mapping_version,
    )
    assert proposal.source_concept == concept
    decision = evaluate(request, store)
    assert decision.status == "approved" and not decision.reason_codes
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field=role,
        mapping=decision.mapping,
    )
    assert len(candidates) == 1
    assert candidates[0].value == Decimal("31067000000")
    assert candidates[0].decimals == -6


@pytest.mark.parametrize("role,concept", PAIRS)
@pytest.mark.parametrize(
    "change,reason",
    (
        (
            {"namespace_uri": "http://fasb.org/us-gaap/2022"},
            "MAPPING_NAMESPACE_UNSUPPORTED",
        ),
        ({"value": "-1"}, "MAPPING_VALUE_INVALID"),
        ({"decimals": None}, "MAPPING_PRECISION_UNAVAILABLE"),
        ({"entity_identifier": "999999"}, "MAPPING_ISSUER_MISMATCH"),
        ({"instant": date(2026, 12, 31)}, "MAPPING_PERIOD_AFTER_ORIGINAL"),
        ({"unit": "xbrli:shares"}, "MAPPING_UNIT_UNSUPPORTED"),
        (
            {
                "dimensions": (
                    ("us-gaap:StatementBusinessSegmentsAxis", "example:Segment"),
                )
            },
            "MAPPING_SCOPE_UNSUPPORTED",
        ),
    ),
)
def test_invalid_carrying_observation_refuses(tmp_path, role, concept, change, reason):
    request, store, _, _ = finance_case(tmp_path, role, concept, change=change)
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert reason in {r.reason_code for r in decision.rejected_observations}


@pytest.mark.parametrize("role,concept", PAIRS)
def test_equally_precise_balances_cannot_conflict(tmp_path, role, concept):
    request, store, _, _ = finance_case(
        tmp_path, role, concept, duplicate_value="32000000000"
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert "MAPPING_OBSERVATION_CONFLICT" in decision.reason_codes


@pytest.mark.parametrize("role,concept", PAIRS)
@pytest.mark.parametrize(
    "other",
    (
        "us-gaap:FinanceLeaseLiability",
        "us-gaap:FinanceLeaseLiabilityPaymentsDueNextTwelveMonths",
        "us-gaap:DebtCurrent",
    ),
)
def test_total_or_undiscounted_amount_is_not_a_classified_carrying_balance(
    tmp_path, role, concept, other
):
    request, store, _, _ = finance_case(
        tmp_path, role, concept, change={"concept": other}
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_NO_ELIGIBLE_OBSERVATIONS" in decision.reason_codes


def test_missing_direct_balance_does_not_infer_zero(tmp_path):
    request, _, _, _ = case(tmp_path)
    for role, _ in PAIRS:
        assert (
            automatic_mapping_proposal(
                role,
                original=request.original,
                mapping_version=request.proposal.mapping_version,
            )
            is None
        )
