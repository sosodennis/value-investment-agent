from __future__ import annotations

from ...extract.extractor import SearchType
from ..mapping import BS_STATEMENT_TOKENS, USD_UNITS, FieldSpec, XbrlMappingRegistry


def register_base_debt_fields(registry: XbrlMappingRegistry) -> None:
    registry.register(
        "total_debt_combined",
        FieldSpec(
            name="Total Debt (Combined, Excluding Finance Leases)",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:DebtLongTermAndShortTermCombinedAmount",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:Debt",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:LongTermDebtAndNotesPayable",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:NotesPayable",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "total_debt_including_finance_leases_combined",
        FieldSpec(
            name="Total Debt (Combined, Including Finance Leases)",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:LongTermDebtAndCapitalLeaseObligations",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:LongTermDebtAndFinanceLeaseLiabilities",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:DebtAndFinanceLeaseLiabilities",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "debt_short",
        FieldSpec(
            name="Short-Term Debt",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:ShortTermBorrowings",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:DebtCurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:LongTermDebtCurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:NotesPayableCurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:LoansPayableCurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:LoansPayable",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:CommercialPaper",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:ShortTermBankLoansAndNotesPayable",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "debt_long",
        FieldSpec(
            name="Long-Term Debt",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:LongTermDebtNoncurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:LongTermDebt",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:LongTermDebtAndNotesPayable",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:NotesPayableNoncurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:NotesPayable",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "finance_lease_liabilities_combined",
        FieldSpec(
            name="Finance Lease Liabilities (Combined)",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:FinanceLeaseLiability",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:CapitalLeaseObligations",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "finance_lease_liabilities_current",
        FieldSpec(
            name="Finance Lease Liabilities (Current)",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:FinanceLeaseLiabilityCurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:CapitalLeaseObligationsCurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "finance_lease_liabilities_noncurrent",
        FieldSpec(
            name="Finance Lease Liabilities (Noncurrent)",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:FinanceLeaseLiabilityNoncurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:CapitalLeaseObligationsNoncurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "notes_payable",
        FieldSpec(
            name="Notes Payable",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:NotesPayable",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "notes_payable_current",
        FieldSpec(
            name="Notes Payable (Current)",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:NotesPayableCurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "notes_payable_noncurrent",
        FieldSpec(
            name="Notes Payable (Noncurrent)",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:NotesPayableNoncurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "loans_payable",
        FieldSpec(
            name="Loans Payable",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:LoansPayable",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "loans_payable_current",
        FieldSpec(
            name="Loans Payable (Current)",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:LoansPayableCurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "commercial_paper",
        FieldSpec(
            name="Commercial Paper",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:CommercialPaper",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "preferred_stock",
        FieldSpec(
            name="Preferred Stock",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:PreferredStockValue",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:PreferredStockCarryingAmount",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:PreferredStock",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )
