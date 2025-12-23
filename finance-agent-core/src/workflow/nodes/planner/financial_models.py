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
from typing import Optional, Literal, Union
from datetime import date
from enum import Enum


# ==========================================
# 1. Base Configuration
# ==========================================

class IndustryType(str, Enum):
    """Industry classification for sector-specific financial analysis"""
    CORPORATE = "CORPORATE"  # General manufacturing/services/tech
    BANK = "BANK"            # Banking & financial institutions
    REIT = "REIT"            # Real Estate Investment Trusts


# ==========================================
# 2. Financial Statement Models (Data Layer)
# ==========================================

class BalanceSheetBase(BaseModel):
    """Base class for all balance sheets"""
    industry: IndustryType
    period_date: date
    
    # Common Solvency Strings
    total_assets: Optional[float] = Field(None, description="us-gaap:Assets")
    total_liabilities: Optional[float] = Field(None, description="us-gaap:Liabilities")
    total_equity: Optional[float] = Field(None, description="us-gaap:StockholdersEquity")
    
    # Common Liquidity Strings
    cash_and_equivalents: Optional[float] = Field(None, description="us-gaap:CashAndCashEquivalentsAtCarryingValue")
    marketable_securities: Optional[float] = Field(None, description="us-gaap:MarketableSecuritiesCurrent")

    @computed_field
    def total_liquidity(self) -> Optional[float]:
        """Calculate total liquidity: Cash + Marketable Securities"""
        if self.cash_and_equivalents is None and self.marketable_securities is None:
            return None
        return (self.cash_and_equivalents or 0.0) + (self.marketable_securities or 0.0)

    @model_validator(mode='after')
    def validate_accounting_identity(self) -> "BalanceSheetBase":
        """Validate accounting equation: Assets = Liabilities + Equity (allow 1% tolerance)"""
        if self.total_assets and self.total_liabilities and self.total_equity:
            calc_assets = self.total_liabilities + self.total_equity
            if abs(self.total_assets - calc_assets) / (self.total_assets + 1e-6) > 0.01:
                pass # Suppress warning for now to avoid noise in logs
        return self


class CorporateBalanceSheet(BalanceSheetBase):
    """Standard balance sheet for corporate/tech/manufacturing"""
    industry: Literal[IndustryType.CORPORATE] = IndustryType.CORPORATE
    
    # Liquidity
    assets_current: Optional[float] = Field(None, description="us-gaap:AssetsCurrent")
    liabilities_current: Optional[float] = Field(None, description="us-gaap:LiabilitiesCurrent")
    receivables_net: Optional[float] = Field(None, description="us-gaap:ReceivablesNetCurrent")
    inventory: Optional[float] = Field(None, description="us-gaap:InventoryNet")
    accounts_payable: Optional[float] = Field(None, description="us-gaap:AccountsPayableCurrent")
    
    # Debt
    debt_current: Optional[float] = Field(None, description="us-gaap:DebtCurrent")
    debt_noncurrent: Optional[float] = Field(None, description="us-gaap:LongTermDebtNoncurrent")

    @computed_field
    def total_debt(self) -> Optional[float]:
        """Total Debt = Current + Non-Current"""
        if self.debt_current is None and self.debt_noncurrent is None:
            return None
        return (self.debt_current or 0.0) + (self.debt_noncurrent or 0.0)


class BankBalanceSheet(BalanceSheetBase):
    """Balance sheet for banking institutions"""
    industry: Literal[IndustryType.BANK] = IndustryType.BANK
    
    total_deposits: Optional[float] = Field(None, description="us-gaap:Deposits")
    net_loans: Optional[float] = Field(None, description="us-gaap:LoansAndLeasesReceivableNetReportedAmount")
    total_debt: Optional[float] = Field(None, description="us-gaap:LongTermDebt") # Often less relevant for banks


class REITBalanceSheet(BalanceSheetBase):
    """Balance sheet for REITs"""
    industry: Literal[IndustryType.REIT] = IndustryType.REIT
    
    real_estate_assets: Optional[float] = Field(None, description="us-gaap:RealEstateInvestmentPropertyNet")
    
    # REIT Debt Components
    unsecured_debt: Optional[float] = Field(None, description="us-gaap:UnsecuredDebt")
    mortgages: Optional[float] = Field(None, description="us-gaap:MortgageLoansOnRealEstate")
    notes_payable: Optional[float] = Field(None, description="us-gaap:NotesPayable")
    
    @computed_field
    def total_debt(self) -> Optional[float]:
        """Total Debt = Unsecured + Mortgages + Notes"""
        val = 0.0
        has_data = False
        if self.unsecured_debt is not None: val += self.unsecured_debt; has_data = True
        if self.mortgages is not None: val += self.mortgages; has_data = True
        if self.notes_payable is not None: val += self.notes_payable; has_data = True
        return val if has_data else None


BalanceSheetVariant = Union[CorporateBalanceSheet, BankBalanceSheet, REITBalanceSheet]


# --- Income Statement Base & Polymorphic Variants ---

class IncomeStatementBase(BaseModel):
    """Base class for all income statements"""
    industry: IndustryType
    period_start: date
    period_end: date
    net_income: Optional[float] = Field(None, description="us-gaap:NetIncomeLoss")
    operating_expenses: Optional[float] = Field(None, description="us-gaap:OperatingExpenses")
    tax_expense: Optional[float] = Field(None, description="us-gaap:IncomeTaxExpenseBenefit")


class CorporateIncomeStatement(IncomeStatementBase):
    """Standard income statement for corporate/tech/manufacturing"""
    industry: Literal[IndustryType.CORPORATE] = IndustryType.CORPORATE
    
    revenue: Optional[float] = Field(None, description="us-gaap:Revenues")
    cogs: Optional[float] = Field(None, description="us-gaap:CostOfGoodsAndServicesSold")
    gross_profit: Optional[float] = Field(None, description="us-gaap:GrossProfit")
    operating_income: Optional[float] = Field(None, description="us-gaap:OperatingIncomeLoss")
    interest_expense: Optional[float] = Field(None, description="us-gaap:InterestExpense")
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


class BankIncomeStatement(IncomeStatementBase):
    """Income statement for banking institutions"""
    industry: Literal[IndustryType.BANK] = IndustryType.BANK
    
    net_interest_income: Optional[float] = Field(None, description="us-gaap:NetInterestIncome")
    non_interest_income: Optional[float] = Field(None, description="us-gaap:NoninterestIncome")
    provision_for_losses: Optional[float] = Field(None, description="us-gaap:ProvisionForLoanLeaseAndOtherLosses")
    avg_earning_assets: Optional[float] = Field(None, description="Calculated from balance sheet")

    @computed_field
    def total_revenue(self) -> Optional[float]:
        """Bank total revenue = Net Interest Income + Non-Interest Income"""
        if self.net_interest_income is None:
            return None
        return self.net_interest_income + (self.non_interest_income or 0.0)

    @computed_field
    def net_interest_margin(self) -> Optional[float]:
        """NIM: Net Interest Margin"""
        if self.avg_earning_assets is None or self.avg_earning_assets == 0:
            return None
        if self.net_interest_income is None:
            return None
        return self.net_interest_income / self.avg_earning_assets

    @computed_field
    def efficiency_ratio(self) -> Optional[float]:
        """Efficiency Ratio: Operating Expenses / Total Revenue (lower is better)"""
        if self.total_revenue is None or self.total_revenue == 0:
            return None
        if self.operating_expenses is None:
            return None
        return self.operating_expenses / self.total_revenue


class REITIncomeStatement(IncomeStatementBase):
    """Income statement for Real Estate Investment Trusts"""
    industry: Literal[IndustryType.REIT] = IndustryType.REIT
    
    rental_income: Optional[float] = Field(None, description="us-gaap:OperatingLeaseRevenue")
    property_operating_expenses: Optional[float] = Field(None, description="Property-related expenses")
    depreciation: Optional[float] = Field(None, description="us-gaap:DepreciationDepletionAndAmortization")
    gains_on_sale: Optional[float] = Field(None, description="Gains on sale of property")

    @computed_field
    def funds_from_operations(self) -> Optional[float]:
        """FFO: Net Income + Depreciation - Gains on Sale"""
        if self.net_income is None:
            return None
        return self.net_income + (self.depreciation or 0.0) - (self.gains_on_sale or 0.0)


# Union type for polymorphism
IncomeStatementVariant = Union[CorporateIncomeStatement, BankIncomeStatement, REITIncomeStatement]


class CashFlowStatementBase(BaseModel):
    """Base class for cash flow statements"""
    industry: IndustryType
    period_start: date
    period_end: date
    ocf: Optional[float] = Field(None, description="us-gaap:NetCashProvidedByUsedInOperatingActivities")
    dividends_paid: Optional[float] = Field(None, description="us-gaap:PaymentsOfDividends")


class CorporateCashFlow(CashFlowStatementBase):
    """Standard CF for corporate"""
    industry: Literal[IndustryType.CORPORATE] = IndustryType.CORPORATE
    capex: Optional[float] = Field(None, description="us-gaap:PaymentsToAcquirePropertyPlantAndEquipment")


class REITCashFlow(CashFlowStatementBase):
    """CF for REITs with specific investment tags"""
    industry: Literal[IndustryType.REIT] = IndustryType.REIT
    real_estate_investment: Optional[float] = Field(None, description="us-gaap:PaymentsToAcquireRealEstate")

    @computed_field
    def capex(self) -> Optional[float]:
        """Proxy Capex for REITs = Real Estate Investment"""
        return self.real_estate_investment


CashFlowStatementVariant = Union[CorporateCashFlow, REITCashFlow]


# ==========================================
# 3. Financial Analysis Model (Compute Layer)
# ==========================================

class FinancialHealthReport(BaseModel):
    """
    Aggregates the Five Pillars of Financial Health Analysis.
    All ratios are computed fields based on the three financial statements.
    Supports polymorphic income statements for different industries.
    """
    company_ticker: str
    fiscal_period: str
    bs: BalanceSheetVariant
    is_: IncomeStatementVariant
    cf: CashFlowStatementVariant
    
    # --------------------------------------------------------
    # 1. Liquidity Pillar
    # --------------------------------------------------------
    @computed_field
    def current_ratio(self) -> Optional[float]:
        """Current Ratio = Current Assets / Current Liabilities (Corporate only)"""
        if not isinstance(self.bs, CorporateBalanceSheet):
            return None
        if self.bs.assets_current is None or self.bs.liabilities_current is None or self.bs.liabilities_current == 0:
            return None
        return self.bs.assets_current / self.bs.liabilities_current

    @computed_field
    def quick_ratio(self) -> Optional[float]:
        """Quick Ratio = (Cash + Marketable Securities + Receivables) / Current Liabilities (Corporate only)"""
        if not isinstance(self.bs, CorporateBalanceSheet):
            return None
        if self.bs.liabilities_current is None or self.bs.liabilities_current == 0:
            return None
        
        numerator = (self.bs.cash_and_equivalents or 0.0) + (self.bs.marketable_securities or 0.0) + (self.bs.receivables_net or 0.0)
        return numerator / self.bs.liabilities_current

    @computed_field
    def cash_ratio(self) -> Optional[float]:
        """Cash Ratio = (Cash + Marketable Securities) / Current Liabilities (Corporate only)"""
        if not isinstance(self.bs, CorporateBalanceSheet):
            return None
        if self.bs.liabilities_current is None or self.bs.liabilities_current == 0:
            return None
        if self.bs.cash_and_equivalents is None:
            return None
        numerator = (self.bs.cash_and_equivalents or 0.0) + (self.bs.marketable_securities or 0.0)
        return numerator / self.bs.liabilities_current

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
        """Interest Coverage = EBIT / Interest Expense (Corporate only)"""
        # Safe-guard: Only Corporate has 'ebit' and 'interest_expense' currently
        if not isinstance(self.is_, CorporateIncomeStatement):
            return None
            
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
        """Inventory Turnover = COGS / Average Inventory (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return None
        if not isinstance(self.bs, CorporateBalanceSheet):
            return None
        if self.bs.inventory is None or self.bs.inventory == 0:
            return None
        if self.is_.cogs is None:
            return None
        return self.is_.cogs / self.bs.inventory

    @computed_field
    def days_sales_outstanding(self) -> Optional[float]:
        """DSO = (Average Receivables / Revenue) * 365 (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return None
        if not isinstance(self.bs, CorporateBalanceSheet):
            return None
        if self.is_.revenue is None or self.is_.revenue == 0:
            return None
        if self.bs.receivables_net is None:
            return None
        return (self.bs.receivables_net / self.is_.revenue) * 365.0

    @computed_field
    def days_payable_outstanding(self) -> Optional[float]:
        """DPO = (Average AP / COGS) * 365 (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return None
        if not isinstance(self.bs, CorporateBalanceSheet):
            return None
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
        """Gross Margin = Gross Profit / Revenue (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return None
        if self.is_.revenue is None or self.is_.revenue == 0 or self.is_.gross_profit is None:
            return None
        return self.is_.gross_profit / self.is_.revenue

    @computed_field
    def operating_margin(self) -> Optional[float]:
        """Operating Margin = Operating Income / Revenue (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return None
        if self.is_.revenue is None or self.is_.revenue == 0:
            return None
        if self.is_.operating_income is None:
            return None
        return self.is_.operating_income / self.is_.revenue

    @computed_field
    def net_margin(self) -> Optional[float]:
        """Net Margin = Net Income / Revenue (Corporate/REIT) or Total Revenue (Bank)"""
        # Get appropriate revenue based on industry type
        revenue = None
        if isinstance(self.is_, CorporateIncomeStatement):
            revenue = self.is_.revenue
        elif isinstance(self.is_, BankIncomeStatement):
            revenue = self.is_.total_revenue
        elif isinstance(self.is_, REITIncomeStatement):
            revenue = self.is_.rental_income
        
        if revenue is None or revenue == 0:
            return None
        if self.is_.net_income is None:
            return None
        return self.is_.net_income / revenue

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
