from __future__ import annotations

from src.agents.fundamental.data.clients.sec_xbrl.extractor import SearchType
from src.agents.fundamental.data.clients.sec_xbrl.factory import (
    BaseFinancialModelFactory,
)
from src.shared.kernel.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
    XBRLProvenance,
)


def _xbrl_field(name: str, value: float | None, concept: str) -> TraceableField[float]:
    return TraceableField(
        name=name,
        value=value,
        provenance=XBRLProvenance(concept=concept, period="instant_2025-12-31"),
    )


def _manual_field(name: str, value: float | None) -> TraceableField[float]:
    return TraceableField(
        name=name,
        value=value,
        provenance=ManualProvenance(description="test"),
    )


def test_total_debt_include_policy_prefers_combined_with_leases() -> None:
    total_debt, _, source = BaseFinancialModelFactory._build_total_debt_with_policy(
        debt_combined_ex_leases=_xbrl_field("Debt Combined", 80.0, "us-gaap:Debt"),
        debt_short=_manual_field("Debt Short", None),
        debt_long=_manual_field("Debt Long", None),
        debt_combined_with_leases=_xbrl_field(
            "Debt + Lease Combined",
            100.0,
            "us-gaap:LongTermDebtAndFinanceLeaseLiabilities",
        ),
        finance_lease_combined=_xbrl_field(
            "Lease Combined", 20.0, "us-gaap:FinanceLeaseLiability"
        ),
        finance_lease_current=_manual_field("Lease Current", None),
        finance_lease_noncurrent=_manual_field("Lease Noncurrent", None),
        policy="include_finance_leases",
    )

    assert total_debt.value == 100.0
    assert source == "combined_debt_including_finance_leases"


def test_total_debt_include_policy_falls_back_to_debt_plus_lease() -> None:
    total_debt, _, source = BaseFinancialModelFactory._build_total_debt_with_policy(
        debt_combined_ex_leases=_manual_field("Debt Combined", None),
        debt_short=_xbrl_field("Debt Short", 30.0, "us-gaap:DebtCurrent"),
        debt_long=_xbrl_field("Debt Long", 50.0, "us-gaap:LongTermDebtNoncurrent"),
        debt_combined_with_leases=_manual_field("Debt + Lease Combined", None),
        finance_lease_combined=_manual_field("Lease Combined", None),
        finance_lease_current=_xbrl_field(
            "Lease Current", 5.0, "us-gaap:FinanceLeaseLiabilityCurrent"
        ),
        finance_lease_noncurrent=_xbrl_field(
            "Lease Noncurrent", 15.0, "us-gaap:FinanceLeaseLiabilityNoncurrent"
        ),
        policy="include_finance_leases",
    )

    assert total_debt.value == 100.0
    assert source == "debt_excluding_finance_leases_plus_finance_lease"


def test_total_debt_exclude_policy_ignores_finance_lease() -> None:
    total_debt, _, source = BaseFinancialModelFactory._build_total_debt_with_policy(
        debt_combined_ex_leases=_manual_field("Debt Combined", None),
        debt_short=_xbrl_field("Debt Short", 40.0, "us-gaap:DebtCurrent"),
        debt_long=_xbrl_field("Debt Long", 60.0, "us-gaap:LongTermDebtNoncurrent"),
        debt_combined_with_leases=_xbrl_field(
            "Debt + Lease Combined",
            125.0,
            "us-gaap:LongTermDebtAndFinanceLeaseLiabilities",
        ),
        finance_lease_combined=_xbrl_field(
            "Lease Combined", 25.0, "us-gaap:FinanceLeaseLiability"
        ),
        finance_lease_current=_manual_field("Lease Current", None),
        finance_lease_noncurrent=_manual_field("Lease Noncurrent", None),
        policy="exclude_finance_leases",
    )

    assert total_debt.value == 100.0
    assert source == "debt_excluding_finance_leases"


def test_resolve_total_debt_policy_defaults_on_invalid_value(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FUNDAMENTAL_TOTAL_DEBT_POLICY", "bad_policy")
    policy = BaseFinancialModelFactory._resolve_total_debt_policy()
    assert policy == "include_finance_leases"


def test_relax_statement_filters_clears_statement_tokens() -> None:
    strict = [
        SearchType.CONSOLIDATED(
            "us-gaap:DebtCurrent",
            statement_types=["balance"],
            period_type="instant",
            unit_whitelist=["usd"],
            respect_anchor_date=False,
        )
    ]
    relaxed = BaseFinancialModelFactory._relax_statement_filters(strict)
    assert relaxed[0].statement_types is None
    assert relaxed[0].period_type == "instant"
    assert relaxed[0].unit_whitelist == ["usd"]
    assert relaxed[0].respect_anchor_date is False


def test_real_estate_debt_combined_prefers_note_split_and_adds_components() -> None:
    total = BaseFinancialModelFactory._build_real_estate_debt_combined_ex_leases(
        notes_payable=_xbrl_field("Notes Payable", 80.0, "us-gaap:NotesPayable"),
        notes_payable_current=_xbrl_field(
            "Notes Payable (Current)", 30.0, "us-gaap:NotesPayableCurrent"
        ),
        notes_payable_noncurrent=_xbrl_field(
            "Notes Payable (Noncurrent)",
            50.0,
            "us-gaap:NotesPayableNoncurrent",
        ),
        loans_payable=_xbrl_field("Loans Payable", 40.0, "us-gaap:LoansPayable"),
        loans_payable_current=_manual_field("Loans Payable (Current)", None),
        commercial_paper=_xbrl_field(
            "Commercial Paper", 10.0, "us-gaap:CommercialPaper"
        ),
    )

    assert total.value == 130.0
    assert isinstance(total.provenance, ComputedProvenance)
    assert (
        total.provenance.expression
        == "Notes Payable + Loans Payable + Commercial Paper"
    )


def test_real_estate_debt_combined_deduplicates_same_tag_period_and_value() -> None:
    total = BaseFinancialModelFactory._build_real_estate_debt_combined_ex_leases(
        notes_payable=_xbrl_field("Notes Payable", 100.0, "us-gaap:NotesPayable"),
        notes_payable_current=_manual_field("Notes Payable (Current)", None),
        notes_payable_noncurrent=_manual_field("Notes Payable (Noncurrent)", None),
        loans_payable=_xbrl_field("Loans Payable", 100.0, "us-gaap:NotesPayable"),
        loans_payable_current=_manual_field("Loans Payable (Current)", None),
        commercial_paper=_manual_field("Commercial Paper", None),
    )

    assert total.value == 100.0
    assert isinstance(total.provenance, XBRLProvenance)
    assert total.provenance.concept == "us-gaap:NotesPayable"
