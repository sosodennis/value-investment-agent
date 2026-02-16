from __future__ import annotations

from pydantic import BaseModel

from src.shared.kernel.traceable import (
    ManualProvenance,
    TraceableField,
)


# --- Base Model (共有字段) ---
class BaseFinancialModel(BaseModel):
    """
    Regardless of industry, these fields are common in SEC filings
    and are used for general health metrics (Net Margin, Debt/Assets, etc.).
    """

    # Context
    ticker: TraceableField[str] = TraceableField(
        name="Ticker",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    cik: TraceableField[str] = TraceableField(
        name="CIK", value=None, provenance=ManualProvenance(description="Initial state")
    )
    company_name: TraceableField[str] = TraceableField(
        name="Company Name",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    sic_code: TraceableField[str] = TraceableField(
        name="SIC Code",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    fiscal_year: TraceableField[str] = TraceableField(
        name="Fiscal Year",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    fiscal_period: TraceableField[str] = TraceableField(
        name="Fiscal Period",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    shares_outstanding: TraceableField[float] = TraceableField(
        name="Shares Outstanding",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )

    # Balance Sheet (BS)
    total_assets: TraceableField[float] = TraceableField(
        name="Total Assets",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    total_liabilities: TraceableField[float] = TraceableField(
        name="Total Liabilities",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    total_equity: TraceableField[float] = TraceableField(
        name="Total Equity",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    cash_and_equivalents: TraceableField[float] = TraceableField(
        name="Cash & Cash Equivalents",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    current_assets: TraceableField[float] = TraceableField(
        name="Current Assets",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    current_liabilities: TraceableField[float] = TraceableField(
        name="Current Liabilities",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    total_debt: TraceableField[float] = TraceableField(
        name="Total Debt",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    preferred_stock: TraceableField[float] = TraceableField(
        name="Preferred Stock",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )

    # Income Statement (IS)
    total_revenue: TraceableField[float] = TraceableField(
        name="Total Revenue",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    operating_income: TraceableField[float] = TraceableField(
        name="Operating Income (EBIT)",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    income_before_tax: TraceableField[float] = TraceableField(
        name="Income Before Tax",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    interest_expense: TraceableField[float] = TraceableField(
        name="Interest Expense",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    depreciation_and_amortization: TraceableField[float] = TraceableField(
        name="Depreciation & Amortization",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    share_based_compensation: TraceableField[float] = TraceableField(
        name="Share-Based Compensation",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    net_income: TraceableField[float] = TraceableField(
        name="Net Income",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    income_tax_expense: TraceableField[float] = TraceableField(
        name="Income Tax Expense",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    ebitda: TraceableField[float] = TraceableField(
        name="EBITDA",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )

    # Cash Flow (CF)
    operating_cash_flow: TraceableField[float] = TraceableField(
        name="Operating Cash Flow (OCF)",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    dividends_paid: TraceableField[float] = TraceableField(
        name="Dividends Paid",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )

    # Derived Metrics (from XBRL fields)
    working_capital: TraceableField[float] = TraceableField(
        name="Working Capital",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    working_capital_delta: TraceableField[float] = TraceableField(
        name="Working Capital Delta",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    effective_tax_rate: TraceableField[float] = TraceableField(
        name="Effective Tax Rate",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    interest_cost_rate: TraceableField[float] = TraceableField(
        name="Interest Cost Rate",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    ebit_margin: TraceableField[float] = TraceableField(
        name="EBIT Margin",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    net_margin: TraceableField[float] = TraceableField(
        name="Net Margin",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    invested_capital: TraceableField[float] = TraceableField(
        name="Invested Capital",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    nopat: TraceableField[float] = TraceableField(
        name="NOPAT",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    roic: TraceableField[float] = TraceableField(
        name="ROIC",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    reinvestment_rate: TraceableField[float] = TraceableField(
        name="Reinvestment Rate",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )


# --- Extension Models (行業特有字段) ---


class IndustrialExtension(BaseModel):
    """
    Applicable for: Manufacturing, Tech, Retail, Software, etc.
    """

    inventory: TraceableField[float] = TraceableField(
        name="Inventory",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    accounts_receivable: TraceableField[float] = TraceableField(
        name="Accounts Receivable",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    cogs: TraceableField[float] = TraceableField(
        name="Cost of Goods Sold (COGS)",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    rd_expense: TraceableField[float] = TraceableField(
        name="R&D Expense",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    sga_expense: TraceableField[float] = TraceableField(
        name="SG&A Expense",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    capex: TraceableField[float] = TraceableField(
        name="Capital Expenditures (CapEx)",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )


class FinancialServicesExtension(BaseModel):
    """
    Applicable for: Banking, Brokers, Financial Services.
    Assets are money, liabilities are deposits.
    """

    loans_and_leases: TraceableField[float] = TraceableField(
        name="Loans and Leases",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    deposits: TraceableField[float] = TraceableField(
        name="Deposits",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    allowance_for_credit_losses: TraceableField[float] = TraceableField(
        name="Allowance for Credit Losses",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    interest_income: TraceableField[float] = TraceableField(
        name="Interest Income",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    interest_expense: TraceableField[float] = TraceableField(
        name="Interest Expense",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    provision_for_loan_losses: TraceableField[float] = TraceableField(
        name="Provision for Loan Losses",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    risk_weighted_assets: TraceableField[float] = TraceableField(
        name="Risk-Weighted Assets",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    tier1_capital_ratio: TraceableField[float] = TraceableField(
        name="Tier 1 Capital Ratio",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )


class RealEstateExtension(BaseModel):
    """
    Applicable for: REITs, Utilities.
    High depreciation, net income often understated.
    """

    real_estate_assets: TraceableField[float] = TraceableField(
        name="Real Estate Assets (at cost)",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    accumulated_depreciation: TraceableField[float] = TraceableField(
        name="Accumulated Depreciation",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    depreciation_and_amortization: TraceableField[float] = TraceableField(
        name="Depreciation & Amortization",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )
    ffo: TraceableField[float] = TraceableField(
        name="FFO (Funds From Operations)",
        value=None,
        provenance=ManualProvenance(description="Initial state"),
    )


# --- Container Model ---


class FinancialReport(BaseModel):
    """
    Aggregated report containing base financial data and industry-specific extension.
    """

    base: BaseFinancialModel
    extension: (
        IndustrialExtension | FinancialServicesExtension | RealEstateExtension | None
    ) = None
    industry_type: str  # e.g., "Industrial", "Financial", "RealEstate", "General"
