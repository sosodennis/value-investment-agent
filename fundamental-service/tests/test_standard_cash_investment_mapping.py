"""Reported cash/current-investment totals supply a single composite exclusion."""

from decimal import Decimal

import pytest

from fundamental_service.automatic_mapping import automatic_mapping_proposal
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from test_automatic_mapping import evaluate
from test_standard_debt_mapping import debt_case

ROLE = "cash_and_short_term_investments"
CONCEPT = "us-gaap:CashCashEquivalentsAndShortTermInvestments"


def cash_case(tmp_path, *, change=None, duplicate_value=None):
    request, store, roots, bundle = debt_case(
        tmp_path,
        change={"concept": CONCEPT, **(change or {})},
        duplicate_value=duplicate_value,
    )
    request = request.model_copy(
        update={
            "proposal": request.proposal.model_copy(
                update={"normalized_field": ROLE, "source_concept": CONCEPT}
            )
        }
    )
    return request, store, roots, bundle


@pytest.mark.parametrize("year", (2023, 2024, 2025, 2026))
def test_reported_total_supplies_one_cash_and_current_investment_exclusion(
    tmp_path, year
):
    request, store, _, _ = cash_case(
        tmp_path, change={"namespace_uri": f"http://fasb.org/us-gaap/{year}"}
    )
    proposal = automatic_mapping_proposal(
        ROLE,
        original=request.original,
        mapping_version=request.proposal.mapping_version,
    )
    assert proposal is not None and proposal.source_concept == CONCEPT
    decision = evaluate(request, store)
    assert decision.status == "approved" and decision.mapping is not None
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


@pytest.mark.parametrize(
    "change,reason",
    (
        (
            {"namespace_uri": "http://fasb.org/us-gaap/2022"},
            "MAPPING_NAMESPACE_UNSUPPORTED",
        ),
        (
            {"namespace_uri": "http://fasb.org/us-gaap/2027"},
            "MAPPING_NAMESPACE_UNSUPPORTED",
        ),
        (
            {"namespace_uri": "https://example.test/us-gaap/2026"},
            "MAPPING_NAMESPACE_UNSUPPORTED",
        ),
        ({"value": "-1"}, "MAPPING_VALUE_INVALID"),
    ),
)
def test_unsupported_total_is_retained_and_refused(tmp_path, change, reason):
    request, store, _, _ = cash_case(tmp_path, change=change)
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert reason in {v.reason_code for v in decision.rejected_observations}


def test_conflicting_cash_totals_refuse(tmp_path):
    request, store, _, _ = cash_case(tmp_path, duplicate_value="32000000000")
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert "MAPPING_OBSERVATION_CONFLICT" in decision.reason_codes


@pytest.mark.parametrize(
    "concept",
    (
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "us-gaap:MarketableSecuritiesCurrent",
    ),
)
def test_partial_balances_do_not_implicitly_supply_the_whole_total(tmp_path, concept):
    request, store, _, _ = cash_case(tmp_path, change={"concept": concept})
    assert (
        automatic_mapping_proposal(
            ROLE,
            original=request.original,
            mapping_version=request.proposal.mapping_version,
        )
        is None
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert "MAPPING_NO_ELIGIBLE_OBSERVATIONS" in decision.reason_codes


def test_registered_proposal_cannot_replace_reported_cash_total(tmp_path):
    from fundamental_service.registered_investment_assets import (
        CASH_AND_SHORT_TERM_INVESTMENTS,
    )

    request, store, _, _ = cash_case(tmp_path)
    request = request.model_copy(
        update={
            "proposal": request.proposal.model_copy(
                update={"source_concept": CASH_AND_SHORT_TERM_INVESTMENTS}
            )
        }
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert "MAPPING_INVESTMENT_DIRECT_REPRESENTATION_REQUIRED" in decision.reason_codes
