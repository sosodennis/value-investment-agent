from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


# 1. 更新來源枚舉
class SourceType(str, Enum):
    XBRL = "XBRL"
    CALCULATION = "CALCULATION"
    MANUAL = "MANUAL"  # <--- 新增這個


# --- 既有的 Provenance ---
class XBRLProvenance(BaseModel):
    type: SourceType = SourceType.XBRL
    concept: str
    period: str


class ComputedProvenance(BaseModel):
    type: SourceType = SourceType.CALCULATION
    op_code: str
    expression: str
    inputs: dict[str, TraceableField]


# --- [新增] ManualProvenance ---
class ManualProvenance(BaseModel):
    type: SourceType = SourceType.MANUAL

    # 這是你要求的核心欄位：解釋「為什麼」要手動輸入
    description: str

    # [建議] 額外加這兩個欄位，讓 Audit Trail 更完整
    author: str | None = "Analyst"  # 誰改的？
    modified_at: str = str(datetime.now())  # 什麼時候改的？


# --- TraceableField Implementation ---


class TraceableFieldBase(BaseModel):
    """
    Base class for TraceableField containing common logic and fields
    that do not depend on the Generic type T at runtime.
    """

    name: str
    provenance: XBRLProvenance | ComputedProvenance | ManualProvenance

    def explain(self, level=0):
        indent = "  " * level
        # Access value safely; subclasses (runtime or static) will have this field
        val = getattr(self, "value", None)
        val_str = f"'{val}'" if isinstance(val, str) else str(val)

        p = self.provenance

        if isinstance(p, XBRLProvenance):
            print(f"{indent}- {self.name}: {val_str} [XBRL: {p.concept}]")

        elif isinstance(p, ComputedProvenance):
            print(f"{indent}- {self.name}: {val_str} [Calc: {p.expression}]")
            for _, field in p.inputs.items():
                if hasattr(field, "explain"):
                    field.explain(level + 1)

        elif isinstance(p, ManualProvenance):
            print(f"{indent}- {self.name}: {val_str} [MANUAL: {p.description}]")


if TYPE_CHECKING:
    # Static Analysis: TraceableField is a Generic Model
    class TraceableField(TraceableFieldBase, Generic[T]):
        value: T | None
else:
    # Runtime: TraceableField is a standard BaseModel (no Generic erasure issues)
    class TraceableField(TraceableFieldBase):
        value: Any | None

        @classmethod
        def __class_getitem__(cls, item):
            return cls


# Resolve forward references for recursive structure
ComputedProvenance.model_rebuild()
TraceableField.model_rebuild()


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

    # Income Statement (IS)
    total_revenue: TraceableField[float] = TraceableField(
        name="Total Revenue",
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

    # Cash Flow (CF)
    operating_cash_flow: TraceableField[float] = TraceableField(
        name="Operating Cash Flow (OCF)",
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
