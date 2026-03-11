from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .extractor import SearchConfig

BuildConfigFn = Callable[
    [str, list[str] | None, str | None, list[str] | None], SearchConfig
]
ResolveConfigsFn = Callable[[str], list[SearchConfig]]
RelaxStatementFiltersFn = Callable[[list[SearchConfig]], list[SearchConfig]]


@dataclass(frozen=True)
class DebtConfigBundle:
    debt_combined: list[SearchConfig]
    debt_combined_with_leases: list[SearchConfig]
    debt_short: list[SearchConfig]
    debt_long: list[SearchConfig]
    notes_payable: list[SearchConfig]
    notes_payable_current: list[SearchConfig]
    notes_payable_noncurrent: list[SearchConfig]
    loans_payable: list[SearchConfig]
    loans_payable_current: list[SearchConfig]
    commercial_paper: list[SearchConfig]
    finance_lease_combined: list[SearchConfig]
    finance_lease_current: list[SearchConfig]
    finance_lease_noncurrent: list[SearchConfig]


def build_debt_config_bundle(
    *,
    resolve_configs: ResolveConfigsFn,
    build_config: BuildConfigFn,
    bs_statement_tokens: list[str],
    usd_units: list[str],
) -> DebtConfigBundle:
    debt_combined = resolve_configs("total_debt_combined") or [
        build_config(
            "us-gaap:DebtLongTermAndShortTermCombinedAmount",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config("us-gaap:Debt", bs_statement_tokens, "instant", usd_units),
        build_config(
            "us-gaap:LongTermDebtAndNotesPayable",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
    ]

    debt_combined_with_leases = resolve_configs(
        "total_debt_including_finance_leases_combined"
    ) or [
        build_config(
            "us-gaap:LongTermDebtAndCapitalLeaseObligations",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:LongTermDebtAndFinanceLeaseLiabilities",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:DebtAndFinanceLeaseLiabilities",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
    ]

    debt_short = resolve_configs("debt_short") or [
        build_config(
            "us-gaap:ShortTermBorrowings",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config("us-gaap:DebtCurrent", bs_statement_tokens, "instant", usd_units),
        build_config(
            "us-gaap:LongTermDebtCurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:NotesPayableCurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:CommercialPaper",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:ShortTermBankLoansAndNotesPayable",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
    ]

    debt_long = resolve_configs("debt_long") or [
        build_config(
            "us-gaap:LongTermDebtNoncurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config("us-gaap:LongTermDebt", bs_statement_tokens, "instant", usd_units),
        build_config(
            "us-gaap:LongTermDebtAndNotesPayable",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:NotesPayableNoncurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config("us-gaap:NotesPayable", bs_statement_tokens, "instant", usd_units),
    ]

    notes_payable = resolve_configs("notes_payable") or [
        build_config("us-gaap:NotesPayable", bs_statement_tokens, "instant", usd_units)
    ]
    notes_payable_current = resolve_configs("notes_payable_current") or [
        build_config(
            "us-gaap:NotesPayableCurrent", bs_statement_tokens, "instant", usd_units
        )
    ]
    notes_payable_noncurrent = resolve_configs("notes_payable_noncurrent") or [
        build_config(
            "us-gaap:NotesPayableNoncurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        )
    ]
    loans_payable = resolve_configs("loans_payable") or [
        build_config("us-gaap:LoansPayable", bs_statement_tokens, "instant", usd_units)
    ]
    loans_payable_current = resolve_configs("loans_payable_current") or [
        build_config(
            "us-gaap:LoansPayableCurrent", bs_statement_tokens, "instant", usd_units
        )
    ]
    commercial_paper = resolve_configs("commercial_paper") or [
        build_config(
            "us-gaap:CommercialPaper", bs_statement_tokens, "instant", usd_units
        )
    ]

    finance_lease_combined = resolve_configs("finance_lease_liabilities_combined") or [
        build_config(
            "us-gaap:FinanceLeaseLiability", bs_statement_tokens, "instant", usd_units
        ),
        build_config(
            "us-gaap:CapitalLeaseObligations",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
    ]
    finance_lease_current = resolve_configs("finance_lease_liabilities_current") or [
        build_config(
            "us-gaap:FinanceLeaseLiabilityCurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:CapitalLeaseObligationsCurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
    ]
    finance_lease_noncurrent = resolve_configs(
        "finance_lease_liabilities_noncurrent"
    ) or [
        build_config(
            "us-gaap:FinanceLeaseLiabilityNoncurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:CapitalLeaseObligationsNoncurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
    ]

    return DebtConfigBundle(
        debt_combined=debt_combined,
        debt_combined_with_leases=debt_combined_with_leases,
        debt_short=debt_short,
        debt_long=debt_long,
        notes_payable=notes_payable,
        notes_payable_current=notes_payable_current,
        notes_payable_noncurrent=notes_payable_noncurrent,
        loans_payable=loans_payable,
        loans_payable_current=loans_payable_current,
        commercial_paper=commercial_paper,
        finance_lease_combined=finance_lease_combined,
        finance_lease_current=finance_lease_current,
        finance_lease_noncurrent=finance_lease_noncurrent,
    )


def relax_debt_config_bundle(
    bundle: DebtConfigBundle,
    relax_statement_filters_fn: RelaxStatementFiltersFn,
) -> DebtConfigBundle:
    return DebtConfigBundle(
        debt_combined=relax_statement_filters_fn(bundle.debt_combined),
        debt_combined_with_leases=relax_statement_filters_fn(
            bundle.debt_combined_with_leases
        ),
        debt_short=relax_statement_filters_fn(bundle.debt_short),
        debt_long=relax_statement_filters_fn(bundle.debt_long),
        notes_payable=relax_statement_filters_fn(bundle.notes_payable),
        notes_payable_current=relax_statement_filters_fn(bundle.notes_payable_current),
        notes_payable_noncurrent=relax_statement_filters_fn(
            bundle.notes_payable_noncurrent
        ),
        loans_payable=relax_statement_filters_fn(bundle.loans_payable),
        loans_payable_current=relax_statement_filters_fn(bundle.loans_payable_current),
        commercial_paper=relax_statement_filters_fn(bundle.commercial_paper),
        finance_lease_combined=relax_statement_filters_fn(
            bundle.finance_lease_combined
        ),
        finance_lease_current=relax_statement_filters_fn(bundle.finance_lease_current),
        finance_lease_noncurrent=relax_statement_filters_fn(
            bundle.finance_lease_noncurrent
        ),
    )
