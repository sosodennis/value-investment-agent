from __future__ import annotations

from dataclasses import dataclass

from .extractor import SearchConfig, SearchType


@dataclass(frozen=True)
class FieldSpec:
    name: str
    configs: list[SearchConfig]


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

    def register(self, field_key: str, spec: FieldSpec) -> None:
        self._fields[field_key] = spec

    def register_override(self, industry: str, field_key: str, spec: FieldSpec) -> None:
        if industry not in self._industry_overrides:
            self._industry_overrides[industry] = {}
        self._industry_overrides[industry][field_key] = spec

    def get(self, field_key: str, industry: str | None = None) -> FieldSpec | None:
        if industry:
            overrides = self._industry_overrides.get(industry, {})
            if field_key in overrides:
                return overrides[field_key]
        return self._fields.get(field_key)

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
            ),
            SearchType.CONSOLIDATED(
                "us-gaap:CommonStockSharesOutstanding",
                unit_whitelist=SHARES_UNITS,
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
        name="Total Debt (Combined)",
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
                "us-gaap:LongTermDebtAndCapitalLeaseObligations",
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
                "us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent",
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
                "us-gaap:LongTermDebtAndCapitalLeaseObligations",
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
