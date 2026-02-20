from __future__ import annotations

from dataclasses import dataclass

from .extractor import SearchConfig, SearchType


@dataclass(frozen=True)
class FieldSpec:
    name: str
    configs: list[SearchConfig]


@dataclass(frozen=True)
class ResolvedFieldSpec:
    field_key: str
    spec: FieldSpec
    source: str  # "issuer_override" | "industry_override" | "base"
    industry: str | None = None
    issuer: str | None = None


USD_UNITS = ["usd"]
SHARES_UNITS = ["shares"]
PURE_UNITS = ["pure"]

BS_STATEMENT_TOKENS = ["balance", "financial position"]
IS_STATEMENT_TOKENS = ["income", "operation", "earning"]
CF_STATEMENT_TOKENS = ["cash"]


class XbrlMappingRegistry:
    def __init__(self) -> None:
        self._fields: dict[str, FieldSpec] = {}
        self._industry_overrides: dict[str, dict[str, FieldSpec]] = {}
        self._issuer_overrides: dict[str, dict[str, FieldSpec]] = {}

    def register(self, field_key: str, spec: FieldSpec) -> None:
        self._fields[field_key] = spec

    def register_override(self, industry: str, field_key: str, spec: FieldSpec) -> None:
        self.register_industry_override(industry, field_key, spec)

    def register_industry_override(
        self, industry: str, field_key: str, spec: FieldSpec
    ) -> None:
        if industry not in self._industry_overrides:
            self._industry_overrides[industry] = {}
        self._industry_overrides[industry][field_key] = spec

    def register_issuer_override(
        self, issuer: str, field_key: str, spec: FieldSpec
    ) -> None:
        normalized_issuer = self._normalize_issuer(issuer)
        if normalized_issuer not in self._issuer_overrides:
            self._issuer_overrides[normalized_issuer] = {}
        self._issuer_overrides[normalized_issuer][field_key] = spec

    @staticmethod
    def _normalize_issuer(issuer: str) -> str:
        return issuer.strip().upper()

    def resolve(
        self,
        field_key: str,
        *,
        industry: str | None = None,
        issuer: str | None = None,
    ) -> ResolvedFieldSpec | None:
        if issuer:
            normalized_issuer = self._normalize_issuer(issuer)
            issuer_overrides = self._issuer_overrides.get(normalized_issuer, {})
            if field_key in issuer_overrides:
                return ResolvedFieldSpec(
                    field_key=field_key,
                    spec=issuer_overrides[field_key],
                    source="issuer_override",
                    industry=industry,
                    issuer=normalized_issuer,
                )

        if industry:
            industry_overrides = self._industry_overrides.get(industry, {})
            if field_key in industry_overrides:
                return ResolvedFieldSpec(
                    field_key=field_key,
                    spec=industry_overrides[field_key],
                    source="industry_override",
                    industry=industry,
                    issuer=self._normalize_issuer(issuer) if issuer else None,
                )

        base_spec = self._fields.get(field_key)
        if base_spec is None:
            return None
        return ResolvedFieldSpec(
            field_key=field_key,
            spec=base_spec,
            source="base",
            industry=industry,
            issuer=self._normalize_issuer(issuer) if issuer else None,
        )

    def get(self, field_key: str, industry: str | None = None) -> FieldSpec | None:
        resolved = self.resolve(field_key, industry=industry)
        if not resolved:
            return None
        return resolved.spec

    def list_fields(self) -> list[str]:
        return sorted(self._fields.keys())


REGISTRY = XbrlMappingRegistry()


# ---- Base fields ----
REGISTRY.register(
    "shares_outstanding",
    FieldSpec(
        name="Shares Outstanding",
        configs=[
            SearchType.CONSOLIDATED(
                "dei:EntityCommonStockSharesOutstanding",
                unit_whitelist=SHARES_UNITS,
                respect_anchor_date=False,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:CommonStockSharesOutstanding",
                unit_whitelist=SHARES_UNITS,
                respect_anchor_date=False,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=SHARES_UNITS,
                respect_anchor_date=False,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=SHARES_UNITS,
                respect_anchor_date=False,
            ),
        ],
    ),
)

REGISTRY.register(
    "total_assets",
    FieldSpec(
        name="Total Assets",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:Assets",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "total_liabilities",
    FieldSpec(
        name="Total Liabilities",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:Liabilities",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "total_equity",
    FieldSpec(
        name="Total Equity",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:StockholdersEquity",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "cash_and_equivalents",
    FieldSpec(
        name="Cash & Cash Equivalents",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:CashAndCashEquivalentsAtCarryingValue",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:CashAndCashEquivalents",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:CashAndCashEquivalentsRestrictedCashAndCashEquivalents",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:Cash",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:CashAndDueFromBanks",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:CashAndDueFromBanksAndInterestBearingDeposits",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:CashEquivalentsAtCarryingValue",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "current_assets",
    FieldSpec(
        name="Current Assets",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:AssetsCurrent",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "current_liabilities",
    FieldSpec(
        name="Current Liabilities",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:LiabilitiesCurrent",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
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

REGISTRY.register(
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

REGISTRY.register(
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

REGISTRY.register(
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

REGISTRY.register(
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

REGISTRY.register(
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

REGISTRY.register(
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

REGISTRY.register(
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

REGISTRY.register(
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

REGISTRY.register(
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

REGISTRY.register(
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

REGISTRY.register(
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

REGISTRY.register(
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

REGISTRY.register(
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

REGISTRY.register(
    "total_revenue",
    FieldSpec(
        name="Total Revenue",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:Revenues",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:SalesRevenueNet",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:RevenuesNetOfInterestExpense",
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:InterestRevenueExpense",
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "operating_income",
    FieldSpec(
        name="Operating Income (EBIT)",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:OperatingIncomeLoss",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:OperatingIncomeLossContinuingOperations",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "income_before_tax",
    FieldSpec(
        name="Income Before Tax",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:IncomeBeforeTax",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:PretaxIncome",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "interest_expense",
    FieldSpec(
        name="Interest Expense",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:InterestExpense",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:InterestExpenseDebt",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            # US-GAAP 2024+ often reports operating/non-operating interest split.
            SearchType.CONSOLIDATED(
                "us-gaap:InterestExpenseOperating",
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:InterestExpenseNonoperating",
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:FinanceLeaseInterestExpense",
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "depreciation_and_amortization",
    FieldSpec(
        name="Depreciation & Amortization",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:DepreciationAndAmortization",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:DepreciationAndAmortization",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:DepreciationDepletionAndAmortization",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:DepreciationDepletionAndAmortization",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:DepreciationAmortizationAndAccretionNet",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:DepreciationAmortizationAndAccretionNet",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "DepreciationAmortizationAndOther",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:Depreciation",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:Depreciation",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "share_based_compensation",
    FieldSpec(
        name="Share-Based Compensation",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:ShareBasedCompensation",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:ShareBasedCompensation",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:ShareBasedCompensationExpense",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:ShareBasedCompensationExpense",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:ShareBasedCompensationCost",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:ShareBasedCompensationCost",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "net_income",
    FieldSpec(
        name="Net Income",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:NetIncomeLoss",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "income_tax_expense",
    FieldSpec(
        name="Income Tax Expense",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:IncomeTaxExpenseBenefit",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "operating_cash_flow",
    FieldSpec(
        name="Operating Cash Flow",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:NetCashProvidedByUsedInOperatingActivities",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "dividends_paid",
    FieldSpec(
        name="Dividends Paid",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:PaymentsOfDividends",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:PaymentsOfDividendsCommonStock",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:DividendsCommonStockCash",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:DividendsPaid",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

# ---- Industrial extension ----
REGISTRY.register(
    "inventory",
    FieldSpec(
        name="Inventory",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:InventoryNet",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:InventoryGross",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "accounts_receivable",
    FieldSpec(
        name="Accounts Receivable",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:AccountsReceivableNetCurrent",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "cogs",
    FieldSpec(
        name="Cost of Goods Sold",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:CostOfGoodsAndServicesSold",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:CostOfRevenue",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "rd_expense",
    FieldSpec(
        name="R&D Expense",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:ResearchAndDevelopmentExpense",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "sga_expense",
    FieldSpec(
        name="SG&A Expense",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:SellingGeneralAndAdministrativeExpense",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            )
        ],
    ),
)

REGISTRY.register(
    "selling_expense",
    FieldSpec(
        name="Selling Expense",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:SellingExpense",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:SellingAndMarketingExpense",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "ga_expense",
    FieldSpec(
        name="G&A Expense",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:GeneralAndAdministrativeExpense",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "capex",
    FieldSpec(
        name="CapEx",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:PaymentsToAcquireProductiveAssets",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:PaymentsToAcquirePropertyAndEquipment",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

# ---- Financial services extension ----
REGISTRY.register(
    "loans_and_leases",
    FieldSpec(
        name="Loans and Leases",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:LoansAndLeasesReceivableNetReportedAmount",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss",
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "deposits",
    FieldSpec(
        name="Deposits",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:Deposits",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "allowance_for_credit_losses",
    FieldSpec(
        name="Allowance for Credit Losses",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:FinancingReceivableAllowanceForCreditLosses",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:FinancingReceivableAllowanceForCreditLossExcludingAccruedInterest",
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:AllowanceForLoanAndLeaseLosses",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "interest_income",
    FieldSpec(
        name="Interest Income",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:InterestIncome",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:InterestIncomeOperating",
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:InterestIncomeExpenseNet",
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "interest_expense_financial",
    FieldSpec(
        name="Interest Expense",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:InterestExpense",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:InterestExpenseOperating",
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:InterestExpenseNonoperating",
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "provision_for_loan_losses",
    FieldSpec(
        name="Provision for Loan Losses",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:ProvisionForCreditLosses",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:ProvisionForLoanLeaseAndOtherLosses",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "risk_weighted_assets",
    FieldSpec(
        name="Risk-Weighted Assets",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:RiskWeightedAssets",
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "tier1_capital_ratio",
    FieldSpec(
        name="Tier 1 Capital Ratio",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:Tier1CapitalRatio",
                period_type="instant",
                unit_whitelist=PURE_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:Tier1RiskBasedCapitalRatio",
                period_type="instant",
                unit_whitelist=PURE_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:TierOneRiskBasedCapitalToRiskWeightedAssets",
                period_type="instant",
                unit_whitelist=PURE_UNITS,
            ),
        ],
    ),
)

# ---- Real estate extension ----
REGISTRY.register(
    "real_estate_assets",
    FieldSpec(
        name="Real Estate Assets (at cost)",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:RealEstateInvestmentPropertyNet",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "accumulated_depreciation",
    FieldSpec(
        name="Accumulated Depreciation",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:RealEstateInvestmentPropertyAccumulatedDepreciation",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "real_estate_dep_amort",
    FieldSpec(
        name="Depreciation & Amortization",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:DepreciationAndAmortizationInRealEstate",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:DepreciationAndAmortization",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:DepreciationDepletionAndAmortization",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

REGISTRY.register(
    "gain_on_sale",
    FieldSpec(
        name="Gain on Sale of Properties",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:GainLossOnSaleOfRealEstateInvestmentProperty",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:GainLossOnSaleOfProperties",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)


# ---- Industry overrides ----
# Financial Services: prioritize bank-specific cash definitions
REGISTRY.register_override(
    "Financial Services",
    "cash_and_equivalents",
    FieldSpec(
        name="Cash & Cash Equivalents",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:CashAndDueFromBanks",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:CashAndDueFromBanksAndInterestBearingDeposits",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:Cash",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:CashAndCashEquivalentsAtCarryingValue",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:CashAndCashEquivalents",
                statement_types=BS_STATEMENT_TOKENS,
                period_type="instant",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)

# Real Estate (REIT): prioritize real-estate specific D&A
REGISTRY.register_override(
    "Real Estate",
    "depreciation_and_amortization",
    FieldSpec(
        name="Depreciation & Amortization",
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:DepreciationAndAmortizationInRealEstate",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:DepreciationAndAmortization",
                statement_types=IS_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:DepreciationAndAmortization",
                statement_types=CF_STATEMENT_TOKENS,
                period_type="duration",
                unit_whitelist=USD_UNITS,
            ),
        ],
    ),
)
