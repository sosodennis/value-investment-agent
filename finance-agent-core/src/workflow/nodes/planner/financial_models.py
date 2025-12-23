"""
Financial Health Check Models - Pydantic V2 Implementation.

Based on research-planner-0.md, implements the five pillars:
1. Liquidity
2. Solvency
3. Operational Efficiency
4. Profitability
5. Cash Flow Quality
"""

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator
from typing import Optional
from datetime import date
from enum import Enum


# ==========================================
# 1. Base Configuration
# ==========================================

class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    CNY = "CNY"


# ==========================================
# 2. Financial Statement Models (Data Layer)
# ==========================================

class BalanceSheet(BaseModel):
    """
    Balance Sheet Model (Instant Context - Point in Time Data)
    Maps XBRL tags to standardized fields with fallback logic.
    """
    period_date: date
    
    # --- Liquidity Inputs ---
    assets_current: Optional[float] = Field(None, description="us-gaap:AssetsCurrent")
    liabilities_current: Optional[float] = Field(None, description="us-gaap:LiabilitiesCurrent")
    cash_and_equivalents: Optional[float] = Field(None, description="us-gaap:CashAndCashEquivalentsAtCarryingValue")
    receivables_net: Optional[float] = Field(None, description="us-gaap:ReceivablesNetCurrent")
    inventory: Optional[float] = Field(None, description="us-gaap:InventoryNet")
    marketable_securities: Optional[float] = Field(None, description="us-gaap:MarketableSecuritiesCurrent")
    
    # --- Solvency Inputs ---
    total_assets: Optional[float] = Field(None, description="us-gaap:Assets")
    total_liabilities: Optional[float] = Field(None, description="us-gaap:Liabilities")
    total_equity: Optional[float] = Field(None, description="us-gaap:StockholdersEquity (Parent)")
    debt_current: Optional[float] = Field(None, description="us-gaap:DebtCurrent")
    debt_noncurrent: Optional[float] = Field(None, description="us-gaap:LongTermDebtNoncurrent")
    
    # --- Efficiency Inputs ---
    accounts_payable: Optional[float] = Field(None, description="us-gaap:AccountsPayableCurrent")

    @computed_field
    def total_debt(self) -> Optional[float]:
        """Calculate total debt: short-term + long-term"""
        if self.debt_current is None and self.debt_noncurrent is None:
            return None
        return (self.debt_current or 0.0) + (self.debt_noncurrent or 0.0)

    @computed_field
    def total_liquidity(self) -> Optional[float]:
        """Calculate total liquidity: Cash + Marketable Securities"""
        if self.cash_and_equivalents is None and self.marketable_securities is None:
            return None
        return (self.cash_and_equivalents or 0.0) + (self.marketable_securities or 0.0)

    @model_validator(mode='after')
    def validate_accounting_identity(self) -> "BalanceSheet":
        """Validate accounting equation: Assets = Liabilities + Equity (allow 1% tolerance)"""
        if self.total_assets and self.total_liabilities and self.total_equity:
            calc_assets = self.total_liabilities + self.total_equity
            if abs(self.total_assets - calc_assets) / (self.total_assets + 1e-6) > 0.01:
                print(f"⚠️  Accounting identity breach. Reported Assets: {self.total_assets:,.0f}, Calc: {calc_assets:,.0f}")
        return self


class IncomeStatement(BaseModel):
    """
    Income Statement Model (Duration Context - Period Data)
    """
    period_start: date
    period_end: date
    
    # --- Efficiency & Profitability Inputs ---
    revenue: Optional[float] = Field(None, description="us-gaap:Revenues / RevenueFromContract...")
    cogs: Optional[float] = Field(None, description="us-gaap:CostOfGoodsAndServicesSold")
    gross_profit: Optional[float] = Field(None, description="us-gaap:GrossProfit")
    operating_expenses: Optional[float] = Field(None, description="us-gaap:OperatingExpenses")
    operating_income: Optional[float] = Field(None, description="us-gaap:OperatingIncomeLoss")
    net_income: Optional[float] = Field(None, description="us-gaap:NetIncomeLoss")
    interest_expense: Optional[float] = Field(None, description="us-gaap:InterestExpense")
    tax_expense: Optional[float] = Field(None, description="us-gaap:IncomeTaxExpenseBenefit")
    depreciation_amortization: Optional[float] = Field(None, description="us-gaap:DepreciationDepletionAndAmortization")

    @field_validator('gross_profit', mode='before')
    @classmethod
    def calculate_gross_profit(cls, v: Optional[float], info) -> Optional[float]:
        """Auto-calculate gross profit if not reported in XBRL"""
        if v is None:
            vals = info.data
            revenue = vals.get('revenue')
            cogs = vals.get('cogs')
            if revenue is not None and cogs is not None:
                return revenue - cogs
        return v

    @computed_field
    def ebit(self) -> Optional[float]:
        """Calculate EBIT (Earnings Before Interest & Tax)"""
        if self.net_income is None: 
            return None
        return self.net_income + (self.interest_expense or 0.0) + (self.tax_expense or 0.0)

    @computed_field
    def ebitda(self) -> Optional[float]:
        """Calculate EBITDA (Earnings Before Interest, Tax, Depreciation & Amortization)"""
        if self.ebit is None:
            return None
        return self.ebit + (self.depreciation_amortization or 0.0)


class CashFlowStatement(BaseModel):
    """
    Cash Flow Statement Model (Duration Context - Period Data)
    """
    period_start: date
    period_end: date
    
    ocf: Optional[float] = Field(None, description="us-gaap:NetCashProvidedByUsedInOperatingActivities")
    capex: Optional[float] = Field(None, description="us-gaap:PaymentsToAcquirePropertyPlantAndEquipment")
    dividends_paid: Optional[float] = Field(None, description="us-gaap:PaymentsOfDividends")


# ==========================================
# 3. Financial Analysis Model (Compute Layer)
# ==========================================

class FinancialHealthReport(BaseModel):
    """
    Aggregates the Five Pillars of Financial Health Analysis.
    All ratios are computed fields based on the three financial statements.
    """
    company_ticker: str
    fiscal_period: str
    bs: BalanceSheet
    is_: IncomeStatement
    cf: CashFlowStatement
    
    # --------------------------------------------------------
    # 1. Liquidity Pillar
    # --------------------------------------------------------
    @computed_field
    def current_ratio(self) -> Optional[float]:
        """Current Ratio = Current Assets / Current Liabilities"""
        if self.bs.assets_current is None or self.bs.liabilities_current is None or self.bs.liabilities_current == 0:
            return None
        return self.bs.assets_current / self.bs.liabilities_current

    @computed_field
    def quick_ratio(self) -> Optional[float]:
        """Quick Ratio = (Cash + Marketable Securities + Receivables) / Current Liabilities"""
        if self.bs.liabilities_current is None or self.bs.liabilities_current == 0:
            return None
        # Treat missing numerators as 0 if at least one exists, or return None if all crucial?
        # Let's assume treat as 0 for sum if typically some could be missing.
        # But if cash is missing, that's critical. 
        if self.bs.cash_and_equivalents is None:
            return None
        
        numerator = (self.bs.cash_and_equivalents or 0.0) + (self.bs.marketable_securities or 0.0) + (self.bs.receivables_net or 0.0)
        return numerator / self.bs.liabilities_current

    @computed_field
    def cash_ratio(self) -> Optional[float]:
        """Cash Ratio = (Cash + Marketable Securities) / Current Liabilities"""
        if self.bs.liabilities_current is None or self.bs.liabilities_current == 0:
            return None
        if self.bs.cash_and_equivalents is None:
            return None
        return ((self.bs.cash_and_equivalents or 0.0) + (self.bs.marketable_securities or 0.0)) / self.bs.liabilities_current

    # --------------------------------------------------------
    # 2. Solvency Pillar
    # --------------------------------------------------------
    @computed_field
    def debt_to_equity(self) -> Optional[float]:
        """Debt-to-Equity Ratio = Total Debt / Total Equity"""
        if self.bs.total_equity is None or self.bs.total_equity == 0:
            return None
        if self.bs.total_debt is None:
            return None
        return self.bs.total_debt / self.bs.total_equity

    @computed_field
    def interest_coverage(self) -> Optional[float]:
        """Interest Coverage = EBIT / Interest Expense"""
        if self.is_.interest_expense is None or self.is_.interest_expense == 0:
            return None
        if self.is_.ebit is None:
            return None
        return self.is_.ebit / self.is_.interest_expense

    @computed_field
    def equity_multiplier(self) -> Optional[float]:
        """Equity Multiplier = Total Assets / Total Equity (DuPont component)"""
        if self.bs.total_equity is None or self.bs.total_equity == 0:
            return None
        if self.bs.total_assets is None:
            return None
        return self.bs.total_assets / self.bs.total_equity

    # --------------------------------------------------------
    # 3. Operational Efficiency Pillar
    # --------------------------------------------------------
    @computed_field
    def inventory_turnover(self) -> Optional[float]:
        """Inventory Turnover = COGS / Average Inventory (simplified: period-end inventory)"""
        if self.bs.inventory is None or self.bs.inventory == 0:
            return None
        if self.is_.cogs is None:
            return None
        return self.is_.cogs / self.bs.inventory

    @computed_field
    def days_sales_outstanding(self) -> Optional[float]:
        """DSO = (Average Receivables / Revenue) * 365"""
        if self.is_.revenue is None or self.is_.revenue == 0:
            return None
        if self.bs.receivables_net is None:
            return None
        return (self.bs.receivables_net / self.is_.revenue) * 365.0

    @computed_field
    def days_payable_outstanding(self) -> Optional[float]:
        """DPO = (Average AP / COGS) * 365"""
        if self.is_.cogs is None or self.is_.cogs == 0:
            return None
        if self.bs.accounts_payable is None:
            return None
        return (self.bs.accounts_payable / self.is_.cogs) * 365.0

    # --------------------------------------------------------
    # 4. Profitability Pillar
    # --------------------------------------------------------
    @computed_field
    def gross_margin(self) -> Optional[float]:
        """Gross Margin = Gross Profit / Revenue"""
        if self.is_.revenue is None or self.is_.revenue == 0 or self.is_.gross_profit is None:
            return None
        return self.is_.gross_profit / self.is_.revenue

    @computed_field
    def operating_margin(self) -> Optional[float]:
        """Operating Margin = Operating Income / Revenue"""
        if self.is_.revenue is None or self.is_.revenue == 0:
            return None
        if self.is_.operating_income is None:
            return None
        return self.is_.operating_income / self.is_.revenue

    @computed_field
    def net_margin(self) -> Optional[float]:
        """Net Margin = Net Income / Revenue"""
        if self.is_.revenue is None or self.is_.revenue == 0:
            return None
        if self.is_.net_income is None:
            return None
        return self.is_.net_income / self.is_.revenue

    @computed_field
    def return_on_equity(self) -> Optional[float]:
        """ROE = Net Income / Average Equity (simplified: period-end equity)"""
        if self.bs.total_equity is None or self.bs.total_equity == 0:
            return None
        if self.is_.net_income is None:
            return None
        return self.is_.net_income / self.bs.total_equity

    @computed_field
    def return_on_assets(self) -> Optional[float]:
        """ROA = Net Income / Total Assets"""
        if self.bs.total_assets is None or self.bs.total_assets == 0:
            return None
        if self.is_.net_income is None:
            return None
        return self.is_.net_income / self.bs.total_assets

    # --------------------------------------------------------
    # 5. Cash Flow Quality Pillar
    # --------------------------------------------------------
    @computed_field
    def free_cash_flow(self) -> Optional[float]:
        """FCF = Operating Cash Flow - Capex"""
        if self.cf.ocf is None or self.cf.capex is None:
            return None
        return self.cf.ocf - self.cf.capex

    @computed_field
    def ocf_to_net_income(self) -> Optional[float]:
        """Quality of Earnings = OCF / Net Income (should be > 1.0)"""
        if self.is_.net_income is None or self.is_.net_income == 0:
            return None
        if self.cf.ocf is None:
            return None
        return self.cf.ocf / self.is_.net_income

    @computed_field
    def accruals_ratio(self) -> Optional[float]:
        """Sloan Ratio = (Net Income - OCF) / Total Assets"""
        if self.bs.total_assets is None or self.bs.total_assets == 0:
            return None
        if self.is_.net_income is None or self.cf.ocf is None:
            return None
        return (self.is_.net_income - self.cf.ocf) / self.bs.total_assets
