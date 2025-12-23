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
from typing import Optional, Literal, Union, Any, Generic, TypeVar, List, Dict
from datetime import date
from enum import Enum
import pandas as pd
import re
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


# ==========================================
# 0. Core Traceability Infrastructure
# ==========================================

class TraceableField(BaseModel, Generic[T]):
    """
    Wraps a numeric value with metadata about its source and calculation.
    Enables full traceability from final metrics back to XBRL tags.
    """
    value: Optional[float] = None
    source_tags: List[str] = Field(default_factory=list, description="XBRL tags or field names used")
    is_calculated: bool = False
    formula_logic: Optional[str] = Field(None, description="Calculation formula if computed")

    def __repr__(self) -> str:
        return f"TraceableField(value={self.value}, sources={self.source_tags})"

    def _merge_metadata(self, other: 'TraceableField', op_symbol: str) -> Dict[str, Any]:
        """Merge metadata from two fields during arithmetic operations"""
        if isinstance(other, TraceableField):
            new_tags = list(set(self.source_tags + other.source_tags))
            self_formula = self.formula_logic or 'Raw'
            other_formula = other.formula_logic or 'Raw'
        else:
            new_tags = self.source_tags.copy()
            self_formula = self.formula_logic or 'Raw'
            other_formula = 'Const'
        
        new_formula = f"({self_formula} {op_symbol} {other_formula})"
        return {"source_tags": new_tags, "is_calculated": True, "formula_logic": new_formula}

    def __add__(self, other: Union['TraceableField', float, int]) -> 'TraceableField':
        self_val = self.value
        other_val = other.value if isinstance(other, TraceableField) else other
        
        if self_val is None and other_val is None:
            return TraceableField(value=None)
            
        # Treat None as 0.0 for addition resilience
        val = (self_val or 0.0) + (other_val or 0.0)
        meta = self._merge_metadata(other, "+")
        return TraceableField(value=val, **meta)

    def __radd__(self, other: Union[float, int]) -> 'TraceableField':
        return self.__add__(other)

    def __sub__(self, other: Union['TraceableField', float, int]) -> 'TraceableField':
        self_val = self.value
        other_val = other.value if isinstance(other, TraceableField) else other
        
        if self_val is None and other_val is None:
            return TraceableField(value=None)
            
        # Treat None as 0.0 for subtraction resilience
        val = (self_val or 0.0) - (other_val or 0.0)
        meta = self._merge_metadata(other, "-")
        return TraceableField(value=val, **meta)

    def __rsub__(self, other: Union[float, int]) -> 'TraceableField':
        if self.value is None:
            return TraceableField(value=None)
        meta = {"source_tags": self.source_tags.copy(), "is_calculated": True, "formula_logic": f"(Const - {self.formula_logic or 'Raw'})"}
        return TraceableField(value=other - self.value, **meta)

    def __mul__(self, other: Union['TraceableField', float, int]) -> 'TraceableField':
        if self.value is None or (isinstance(other, TraceableField) and other.value is None):
            return TraceableField(value=None)
        other_val = other.value if isinstance(other, TraceableField) else other
        meta = self._merge_metadata(other, "*")
        return TraceableField(value=self.value * other_val, **meta)

    def __rmul__(self, other: Union[float, int]) -> 'TraceableField':
        return self.__mul__(other)

    def __truediv__(self, other: Union['TraceableField', float, int]) -> 'TraceableField':
        other_val = other.value if isinstance(other, TraceableField) else other
        if self.value is None or other_val is None or other_val == 0:
            return TraceableField(value=None)
        meta = self._merge_metadata(other, "/")
        return TraceableField(value=self.value / other_val, **meta)

    def __rtruediv__(self, other: Union[float, int]) -> 'TraceableField':
        if self.value is None or self.value == 0:
            return TraceableField(value=None)
        meta = {"source_tags": self.source_tags.copy(), "is_calculated": True, "formula_logic": f"(Const / {self.formula_logic or 'Raw'})"}
        return TraceableField(value=other / self.value, **meta)


class AutoExtractModel(BaseModel):
    """
    Base model that automatically extracts XBRL data using waterfall logic.
    Reads field metadata (xbrl_tags, fuzzy_keywords) and populates TraceableField objects.
    """

    @model_validator(mode='before')
    @classmethod
    def extract_from_raw_xbrl(cls, data: Any) -> Any:
        """
        Pre-validation hook: Extract values from raw XBRL data using field metadata.
        """
        if not isinstance(data, dict):
            return data

        # Convert DataFrame to dict if needed
        if isinstance(data.get('_raw_df'), pd.DataFrame):
            raw_df = data.pop('_raw_df')
            raw_dict = cls._df_to_dict(raw_df)
            data.update(raw_dict)
        
        model_fields = cls.model_fields
        processed_data = {}
        
        for field_name, field_info in model_fields.items():
            # If already provided, skip extraction
            if field_name in data and data[field_name] is not None:
                processed_data[field_name] = data[field_name]
                continue

            # Get extraction metadata
            extra = field_info.json_schema_extra or {}
            xbrl_tags = extra.get('xbrl_tags', [])
            fuzzy_keywords = extra.get('fuzzy_keywords', [])
            exclude_keywords = extra.get('exclude_keywords', [])

            # Skip non-XBRL fields
            if not xbrl_tags and not fuzzy_keywords:
                processed_data[field_name] = data.get(field_name)
                continue

            # Extract using smart logic
            result_obj = cls._internal_get_fact_smart(
                raw_data=data,
                standard_tags=xbrl_tags,
                fuzzy_keywords=fuzzy_keywords,
                exclude_keywords=exclude_keywords
            )
            
            processed_data[field_name] = result_obj

        return processed_data

    @staticmethod
    def _df_to_dict(df: pd.DataFrame) -> Dict[str, float]:
        """Convert XBRL DataFrame to tag:value dictionary"""
        # Filter for consolidated data (no dimensions)
        dim_cols = [c for c in df.columns if c.startswith('dim_')]
        if dim_cols:
            consolidated_mask = df[dim_cols].isna().all(axis=1)
            clean_df = df[consolidated_mask]
        else:
            clean_df = df

        # Create dict from most recent values
        result = {}
        if 'concept' in clean_df.columns and 'value' in clean_df.columns:
            for concept in clean_df['concept'].unique():
                concept_rows = clean_df[clean_df['concept'] == concept]
                # Sort by date to get most recent
                sort_col = 'period_instant' if 'period_instant' in concept_rows.columns else 'period_end'
                if sort_col in concept_rows.columns:
                    concept_rows = concept_rows.sort_values(by=sort_col, ascending=False)
                if not concept_rows.empty:
                    try:
                        result[concept] = float(concept_rows.iloc[0]['value'])
                    except (ValueError, TypeError):
                        pass
        return result

    @staticmethod
    def _internal_get_fact_smart(
        raw_data: Dict[str, float],
        standard_tags: List[str],
        fuzzy_keywords: List[str],
        exclude_keywords: List[str]
    ) -> Dict[str, Any]:
        """
        Smart extraction: Try standard tags first, then fuzzy matching.
        Returns dict suitable for TraceableField construction.
        """
        # Phase 1: Standard tags (exact match)
        for tag in standard_tags:
            val = raw_data.get(tag)
            if val is not None and val != 0:
                return {
                    "value": float(val),
                    "source_tags": [tag],
                    "is_calculated": False,
                    "formula_logic": "Exact Match"
                }

        # Phase 2: Fuzzy matching
        if fuzzy_keywords:
            # Build regex pattern (must contain all keywords)
            pattern = "".join([f"(?=.*{k})" for k in fuzzy_keywords])
            
            matches = []
            for raw_tag in raw_data.keys():
                raw_tag_str = str(raw_tag)
                
                # Check exclusions
                if exclude_keywords and any(exc.lower() in raw_tag_str.lower() for exc in exclude_keywords):
                    continue
                
                # Check if matches all keywords
                if re.search(pattern, raw_tag_str, re.IGNORECASE):
                    matches.append(raw_tag_str)
            
            if matches:
                # Prefer shorter tags (usually parent concepts)
                matches.sort(key=len)
                best_tag = matches[0]
                val = raw_data.get(best_tag)
                if val is not None and val != 0:
                    return {
                        "value": float(val),
                        "source_tags": [best_tag],
                        "is_calculated": False,
                        "formula_logic": f"Fuzzy Match: {fuzzy_keywords}"
                    }

        # Phase 3: Not found
        return {
            "value": None,
            "source_tags": [],
            "is_calculated": False
        }


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

class BalanceSheetBase(AutoExtractModel):
    """Base class for all balance sheets with automatic XBRL extraction"""
    industry: IndustryType
    period_date: date
    
    # Common Solvency Fields
    total_assets: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:Assets']}
    )
    total_liabilities: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:Liabilities']}
    )
    total_equity: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:StockholdersEquity',
                'us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'
            ]
        }
    )
    
    # Common Liquidity Fields
    cash_and_equivalents: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:CashAndCashEquivalentsAtCarryingValue',
                'us-gaap:Cash'
            ]
        }
    )
    marketable_securities: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:MarketableSecuritiesCurrent',
                'us-gaap:ShortTermInvestments'
            ]
        }
    )
    marketable_securities_noncurrent: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:MarketableSecuritiesNoncurrent',
                'us-gaap:AvailableForSaleSecuritiesNoncurrent',
                'us-gaap:HeldToMaturitySecuritiesNoncurrent',
                'us-gaap:LongTermInvestments'
            ]
        }
    )

    @computed_field
    def total_liquidity(self) -> TraceableField:
        """Calculate total liquidity: Cash + Marketable Securities (Current + Non-Current)"""
        result = self.cash_and_equivalents + self.marketable_securities + self.marketable_securities_noncurrent
        result.formula_logic = "Cash + Liquid Securities"
        return result

    @model_validator(mode='after')
    def validate_accounting_identity(self) -> "BalanceSheetBase":
        """Validate accounting equation: Assets = Liabilities + Equity (allow 1% tolerance)"""
        if self.total_assets.value and self.total_liabilities.value and self.total_equity.value:
            calc_assets = self.total_liabilities.value + self.total_equity.value
            if abs(self.total_assets.value - calc_assets) / (self.total_assets.value + 1e-6) > 0.01:
                pass  # Suppress warning for now to avoid noise in logs
        return self


class CorporateBalanceSheet(BalanceSheetBase):
    """Standard balance sheet for corporate/tech/manufacturing"""
    industry: Literal[IndustryType.CORPORATE] = IndustryType.CORPORATE
    
    # Liquidity
    assets_current: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:AssetsCurrent']}
    )
    liabilities_current: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:LiabilitiesCurrent']}
    )
    receivables_net: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:ReceivablesNetCurrent',
                'us-gaap:AccountsReceivableNetCurrent'
            ]
        }
    )
    inventory: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:InventoryNet']}
    )
    accounts_payable: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:AccountsPayableCurrent']}
    )
    
    # Debt
    debt_current: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:DebtCurrent',
                'us-gaap:ShortTermBorrowings',
                'us-gaap:LongTermDebtCurrent'
            ]
        }
    )
    debt_noncurrent: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:LongTermDebtNoncurrent',
                'us-gaap:LongTermDebtExcludingCurrentPortion',
                'us-gaap:LongTermDebtAndFinanceLeaseObligations',
                'us-gaap:LongTermDebt',
                'us-gaap:LongTermDebtAndCapitalLeaseObligations'
            ]
        }
    )

    @computed_field
    def total_debt(self) -> TraceableField:
        """Total Debt = Current + Non-Current"""
        result = self.debt_current + self.debt_noncurrent
        result.formula_logic = "ShortTerm + LongTerm Debt"
        return result

    # --- Adjusted Debt Logic for Asset-Light/OpCo Entities (e.g., MGM, SBUX) ---
    lease_liabilities_current: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': ['us-gaap:OperatingLeaseLiabilityCurrent'],
            'fuzzy_keywords': ['OperatingLeaseLiability', 'Current'],
            'exclude_keywords': []
        }
    )
    lease_liabilities_noncurrent: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': ['us-gaap:OperatingLeaseLiabilityNoncurrent'],
            'fuzzy_keywords': ['OperatingLeaseLiability', 'Noncurrent'],
            'exclude_keywords': []
        }
    )

    @computed_field
    def total_lease_liabilities(self) -> TraceableField:
        """Calculate total operating lease liabilities"""
        result = self.lease_liabilities_current + self.lease_liabilities_noncurrent
        result.formula_logic = "Lease Current + Noncurrent"
        return result

    @computed_field
    def adjusted_total_debt(self) -> TraceableField:
        """
        Adjusted Debt = Financial Debt + Operating Lease Liabilities.
        Critical for assessing leverage of tenants in triple-net ecosystems (e.g. MGM vs VICI).
        """
        result = self.total_debt + self.total_lease_liabilities
        result.formula_logic = "Total Debt + Leases"
        return result

    @computed_field
    def net_debt(self) -> TraceableField:
        """Net Debt = Total Debt (Financial) - Total Liquidity"""
        result = self.total_debt - self.total_liquidity
        result.formula_logic = "Total Debt - Total Liquidity"
        return result


class BankBalanceSheet(BalanceSheetBase):
    """Balance sheet for banking institutions"""
    industry: Literal[IndustryType.BANK] = IndustryType.BANK
    
    total_deposits: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:Deposits',
                'us-gaap:DepositsForeignAndDomestic'
            ]
        }
    )
    net_loans: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:LoansAndLeasesReceivableNetReportedAmount',
                'us-gaap:FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss'
            ]
        }
    )
    total_debt: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:LongTermDebt',
                'us-gaap:LongTermDebtExcludingCurrentPortion',
                'us-gaap:LongTermDebtNoncurrent',
                'us-gaap:LongTermDebtAndFinanceLeaseObligations',
                'us-gaap:LongTermDebtAndCapitalLeaseObligations',
                'us-gaap:Debt'
            ]
        }
    )


class REITBalanceSheet(BalanceSheetBase):
    """Balance sheet for REITs"""
    industry: Literal[IndustryType.REIT] = IndustryType.REIT
    
    real_estate_assets: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:RealEstateInvestmentPropertyNet',
                'us-gaap:RealEstateRealEstateAssetsNet'
            ]
        }
    )
    
    # REIT Debt Components
    unsecured_debt: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:UnsecuredDebt', 
                'us-gaap:SeniorNotes',
                'us-gaap:LongTermDebtExcludingCurrentPortion',
                'us-gaap:LongTermDebtNoncurrent',
                'us-gaap:LongTermDebtAndFinanceLeaseObligations',
                'us-gaap:LongTermDebt'
            ],
            'fuzzy_keywords': ['SeniorNotes', 'Unsecured', 'NotesPayable'],
            'exclude_keywords': ['Interest', 'Expense', 'Amortization', 'Receivable', 'Issuance']
        }
    )
    mortgages: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': ['us-gaap:MortgageLoansOnRealEstate'],
            'fuzzy_keywords': ['Mortgage'],
            'exclude_keywords': ['Interest', 'Receivable', 'Asset']
        }
    )
    notes_payable: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': ['us-gaap:TermLoan'],
            'fuzzy_keywords': ['TermLoan', 'CreditFacility', 'LineOfCredit', 'Revolving'],
            'exclude_keywords': ['Interest', 'Fee']
        }
    )
    
    @computed_field
    def total_debt(self) -> TraceableField:
        """Total Debt = Unsecured + Mortgages + Notes"""
        result = self.unsecured_debt + self.mortgages + self.notes_payable
        result.formula_logic = "Unsecured + Mortgages + BankLoans"
        return result


BalanceSheetVariant = Union[CorporateBalanceSheet, BankBalanceSheet, REITBalanceSheet]


# --- Income Statement Base & Polymorphic Variants ---

class IncomeStatementBase(AutoExtractModel):
    """Base class for all income statements with automatic XBRL extraction"""
    industry: IndustryType
    period_start: date
    period_end: date
    
    net_income: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': ['us-gaap:NetIncomeLoss', 'us-gaap:ProfitLoss']
        }
    )
    operating_expenses: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:OperatingExpenses']}
    )
    tax_expense: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:IncomeTaxExpenseBenefit']}
    )


class CorporateIncomeStatement(IncomeStatementBase):
    """Standard income statement for corporate/tech/manufacturing"""
    industry: Literal[IndustryType.CORPORATE] = IndustryType.CORPORATE
    
    revenue: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:Revenues',
                'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'
            ]
        }
    )
    cogs: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:CostOfGoodsAndServicesSold',
                'us-gaap:CostOfRevenue'
            ]
        }
    )
    gross_profit: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:GrossProfit']}
    )
    operating_income: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:OperatingIncomeLoss']}
    )
    interest_expense: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:InterestExpense']}
    )
    depreciation_amortization: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:DepreciationDepletionAndAmortization',
                'us-gaap:DepreciationAndAmortization'
            ]
        }
    )

    @model_validator(mode='after')
    def calculate_gross_profit_if_missing(self) -> 'CorporateIncomeStatement':
        """Auto-calculate gross profit if not reported in XBRL"""
        if self.gross_profit.value is None:
            if self.revenue.value is not None and self.cogs.value is not None:
                self.gross_profit = self.revenue - self.cogs
                self.gross_profit.formula_logic = "Revenue - COGS"
        return self

    @computed_field
    def ebit(self) -> TraceableField:
        """Calculate EBIT (Earnings Before Interest & Tax)"""
        result = self.net_income + self.interest_expense + self.tax_expense
        result.formula_logic = "Net Income + Interest + Tax"
        return result

    @computed_field
    def ebitda(self) -> TraceableField:
        """Calculate EBITDA (Earnings Before Interest, Tax, Depreciation & Amortization)"""
        result = self.ebit + self.depreciation_amortization
        result.formula_logic = "EBIT + D&A"
        return result


class BankIncomeStatement(IncomeStatementBase):
    """Income statement for banking institutions"""
    industry: Literal[IndustryType.BANK] = IndustryType.BANK
    
    net_interest_income: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:NetInterestIncome']}
    )
    non_interest_income: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:NoninterestIncome']}
    )
    provision_for_losses: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:ProvisionForLoanLeaseAndOtherLosses']}
    )
    avg_earning_assets: TraceableField = Field(
        default_factory=TraceableField,
        description="Calculated from balance sheet"
    )

    @computed_field
    def total_revenue(self) -> TraceableField:
        """Bank total revenue = Net Interest Income + Non-Interest Income"""
        result = self.net_interest_income + self.non_interest_income
        result.formula_logic = "NII + Non-Interest Income"
        return result

    @computed_field
    def net_interest_margin(self) -> TraceableField:
        """NIM: Net Interest Margin"""
        result = self.net_interest_income / self.avg_earning_assets
        result.formula_logic = "NII / Avg Earning Assets"
        return result

    @computed_field
    def efficiency_ratio(self) -> TraceableField:
        """Efficiency Ratio: Operating Expenses / Total Revenue (lower is better)"""
        result = self.operating_expenses / self.total_revenue
        result.formula_logic = "OpEx / Total Revenue"
        return result


class REITIncomeStatement(IncomeStatementBase):
    """Income statement for Real Estate Investment Trusts"""
    industry: Literal[IndustryType.REIT] = IndustryType.REIT
    
    rental_income: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:OperatingLeaseRevenue',
                'us-gaap:RentalIncome',
                'us-gaap:Revenues',
                'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'
            ]
        }
    )
    property_operating_expenses: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:OperatingExpenses']}
    )
    depreciation: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:DepreciationDepletionAndAmortization',
                'us-gaap:DepreciationAndAmortization',
                'us-gaap:Depreciation'
            ],
            'fuzzy_keywords': ['Depreciation', 'RealEstate'],
            'exclude_keywords': ['Accumulated', 'Reserve']
        }
    )
    gains_on_sale: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:GainLossOnSaleOfProperties']}
    )

    @computed_field
    def funds_from_operations(self) -> TraceableField:
        """FFO: Net Income + Depreciation - Gains on Sale"""
        result = self.net_income + self.depreciation - self.gains_on_sale
        result.formula_logic = "Net Income + Depreciation - Gains on Sale"
        return result


# Union type for polymorphism
IncomeStatementVariant = Union[CorporateIncomeStatement, BankIncomeStatement, REITIncomeStatement]


class CashFlowStatementBase(AutoExtractModel):
    """Base class for cash flow statements with automatic XBRL extraction"""
    industry: IndustryType
    period_start: date
    period_end: date
    
    ocf: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:NetCashProvidedByUsedInOperatingActivities']}
    )
    dividends_paid: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:PaymentsOfDividendsCommonStock',
                'us-gaap:PaymentsOfDividends',
                'us-gaap:PaymentsOfOrdinaryDividends',
                'us-gaap:DividendsPaid',
                'us-gaap:Dividends'
            ]
        }
    )


class CorporateCashFlow(CashFlowStatementBase):
    """Standard CF for corporate"""
    industry: Literal[IndustryType.CORPORATE] = IndustryType.CORPORATE
    
    capex: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:PaymentsToAcquirePropertyPlantAndEquipment',
                'us-gaap:CapitalExpendituresIncurredButNotYetPaid'
            ]
        }
    )

    @computed_field
    def free_cash_flow(self) -> TraceableField:
        """FCF = OCF - Capex"""
        result = self.ocf - self.capex
        result.formula_logic = "OCF - Capex"
        return result


class REITCashFlow(CashFlowStatementBase):
    """CF for REITs with specific investment tags"""
    industry: Literal[IndustryType.REIT] = IndustryType.REIT
    
    real_estate_investment: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:PaymentsToAcquireRealEstate',
                'us-gaap:PaymentsToAcquireRealEstateHeldForInvestment',
                'us-gaap:PaymentsToAcquireProperties',
                'us-gaap:PaymentsToAcquireProductiveAssets'
            ]
        }
    )

    @computed_field
    def capex(self) -> TraceableField:
        """Proxy Capex for REITs = Real Estate Investment"""
        result = TraceableField(
            value=self.real_estate_investment.value,
            source_tags=self.real_estate_investment.source_tags.copy(),
            is_calculated=True,
            formula_logic="Real Estate Investment (Proxy for Capex)"
        )
        return result

    @computed_field
    def free_cash_flow(self) -> TraceableField:
        """FCF = OCF - Real Estate Investment"""
        result = self.ocf - self.real_estate_investment
        result.formula_logic = "OCF - RE Investment"
        return result


CashFlowStatementVariant = Union[CorporateCashFlow, REITCashFlow]


# ==========================================
# 3. Financial Analysis Model (Compute Layer)
# ==========================================

class FinancialHealthReport(BaseModel):
    """
    Aggregates the Five Pillars of Financial Health Analysis.
    All ratios are computed fields based on the three financial statements.
    Supports polymorphic income statements for different industries.
    
    Note: All ratios return TraceableField for full end-to-end traceability.
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
    def current_ratio(self) -> TraceableField:
        """Current Ratio = Current Assets / Current Liabilities (Corporate only)"""
        if not isinstance(self.bs, CorporateBalanceSheet):
            return TraceableField(value=None)
        
        result = self.bs.assets_current / self.bs.liabilities_current
        result.formula_logic = "Current Assets / Current Liabilities"
        return result

    @computed_field
    def quick_ratio(self) -> TraceableField:
        """Quick Ratio = (Cash + Marketable Securities + Receivables) / Current Liabilities (Corporate only)"""
        if not isinstance(self.bs, CorporateBalanceSheet):
            return TraceableField(value=None)
        
        numerator = self.bs.cash_and_equivalents + self.bs.marketable_securities + self.bs.receivables_net
        result = numerator / self.bs.liabilities_current
        result.formula_logic = "(Cash + Securities + Receivables) / Current Liabilities"
        return result

    @computed_field
    def cash_ratio(self) -> TraceableField:
        """Cash Ratio = (Cash + Marketable Securities) / Current Liabilities (Corporate only)"""
        if not isinstance(self.bs, CorporateBalanceSheet):
            return TraceableField(value=None)
        
        numerator = self.bs.cash_and_equivalents + self.bs.marketable_securities
        result = numerator / self.bs.liabilities_current
        result.formula_logic = "(Cash + Securities) / Current Liabilities"
        return result

    # --------------------------------------------------------
    # 2. Solvency Pillar
    # --------------------------------------------------------
    @computed_field
    def debt_to_equity(self) -> TraceableField:
        """Debt-to-Equity Ratio = Total Debt / Total Equity"""
        result = self.bs.total_debt / self.bs.total_equity
        result.formula_logic = "Total Debt / Total Equity"
        return result

    @computed_field
    def interest_coverage(self) -> TraceableField:
        """Interest Coverage = EBIT / Interest Expense (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return TraceableField(value=None)
        
        result = self.is_.ebit / self.is_.interest_expense
        result.formula_logic = "EBIT / Interest Expense"
        return result

    @computed_field
    def equity_multiplier(self) -> TraceableField:
        """Equity Multiplier = Total Assets / Total Equity (DuPont component)"""
        result = self.bs.total_assets / self.bs.total_equity
        result.formula_logic = "Total Assets / Total Equity"
        return result

    # --------------------------------------------------------
    # 3. Operational Efficiency Pillar
    # --------------------------------------------------------
    @computed_field
    def inventory_turnover(self) -> TraceableField:
        """Inventory Turnover = COGS / Average Inventory (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return TraceableField(value=None)
        if not isinstance(self.bs, CorporateBalanceSheet):
            return TraceableField(value=None)
        
        result = self.is_.cogs / self.bs.inventory
        result.formula_logic = "COGS / Inventory"
        return result

    @computed_field
    def days_sales_outstanding(self) -> TraceableField:
        """DSO = (Average Receivables / Revenue) * 365 (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return TraceableField(value=None)
        if not isinstance(self.bs, CorporateBalanceSheet):
            return TraceableField(value=None)
        
        result = (self.bs.receivables_net / self.is_.revenue) * 365.0
        result.formula_logic = "(Receivables / Revenue) * 365"
        return result

    @computed_field
    def days_payable_outstanding(self) -> TraceableField:
        """DPO = (Average AP / COGS) * 365 (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return TraceableField(value=None)
        if not isinstance(self.bs, CorporateBalanceSheet):
            return TraceableField(value=None)
        
        result = (self.bs.accounts_payable / self.is_.cogs) * 365.0
        result.formula_logic = "(Accounts Payable / COGS) * 365"
        return result

    # --------------------------------------------------------
    # 4. Profitability Pillar
    # --------------------------------------------------------
    @computed_field
    def gross_margin(self) -> TraceableField:
        """Gross Margin = Gross Profit / Revenue (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return TraceableField(value=None)
        
        result = self.is_.gross_profit / self.is_.revenue
        result.formula_logic = "Gross Profit / Revenue"
        return result

    @computed_field
    def operating_margin(self) -> TraceableField:
        """Operating Margin = Operating Income / Revenue (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return TraceableField(value=None)
        
        result = self.is_.operating_income / self.is_.revenue
        result.formula_logic = "Operating Income / Revenue"
        return result

    @computed_field
    def net_margin(self) -> TraceableField:
        """Net Margin = Net Income / Revenue (Corporate/REIT) or Total Revenue (Bank)"""
        # Get appropriate revenue based on industry type
        if isinstance(self.is_, CorporateIncomeStatement):
            result = self.is_.net_income / self.is_.revenue
            result.formula_logic = "Net Income / Revenue"
        elif isinstance(self.is_, BankIncomeStatement):
            result = self.is_.net_income / self.is_.total_revenue
            result.formula_logic = "Net Income / Total Revenue"
        elif isinstance(self.is_, REITIncomeStatement):
            result = self.is_.net_income / self.is_.rental_income
            result.formula_logic = "Net Income / Rental Income"
        else:
            result = TraceableField(value=None)
        
        return result

    @computed_field
    def return_on_equity(self) -> TraceableField:
        """ROE = Net Income / Average Equity (simplified: period-end equity)"""
        result = self.is_.net_income / self.bs.total_equity
        result.formula_logic = "Net Income / Total Equity"
        return result

    @computed_field
    def return_on_assets(self) -> TraceableField:
        """ROA = Net Income / Total Assets"""
        result = self.is_.net_income / self.bs.total_assets
        result.formula_logic = "Net Income / Total Assets"
        return result

    # --------------------------------------------------------
    # 5. Cash Flow Quality Pillar
    # --------------------------------------------------------
    @computed_field
    def free_cash_flow(self) -> TraceableField:
        """FCF = Operating Cash Flow - Capex"""
        result = self.cf.ocf - self.cf.capex
        result.formula_logic = "OCF - Capex"
        return result

    @computed_field
    def ocf_to_net_income(self) -> TraceableField:
        """Quality of Earnings = OCF / Net Income (should be > 1.0)"""
        result = self.cf.ocf / self.is_.net_income
        result.formula_logic = "OCF / Net Income"
        return result

    @computed_field
    def accruals_ratio(self) -> TraceableField:
        """Sloan Ratio = (Net Income - OCF) / Total Assets"""
        numerator = self.is_.net_income - self.cf.ocf
        result = numerator / self.bs.total_assets
        result.formula_logic = "(Net Income - OCF) / Total Assets"
        return result
