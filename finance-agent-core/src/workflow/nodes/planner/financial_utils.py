import logging
import pandas as pd
from typing import Optional, List, Union
from datetime import date, datetime
from edgar import Company, set_identity

from .financial_models import (
    BalanceSheet,
    IncomeStatement,
    CashFlowStatement,
    FinancialHealthReport
)

logger = logging.getLogger(__name__)

# Set SEC EDGAR identity
set_identity("ValueInvestmentAgent research@example.com")


def fetch_financial_data(ticker: str, fiscal_year: Optional[int] = None) -> Optional[FinancialHealthReport]:
    """
    Fetch financial data from SEC EDGAR using edgartools.
    """
    try:
        logger.info(f"Fetching financial data for {ticker} from SEC EDGAR...")
        
        # 1. Get company and latest 10-K filing
        company = Company(ticker)
        filings = company.get_filings(form="10-K")
        
        if not filings:
            logger.warning(f"No 10-K filings found for {ticker}")
            return None
            
        # Get most recent filing
        filing = filings[0]
        logger.info(f"Using 10-K filing: {filing.filing_date}")
        
        # 2. Extract XBRL data as Dataframe
        xbrl = filing.xbrl()
        if not xbrl:
            logger.warning(f"No XBRL data available for {ticker}")
            return None
            
        try:
            facts_df = xbrl.facts.to_dataframe()
        except Exception as e:
            logger.error(f"Failed to convert facts to dataframe: {e}")
            return None
        
        # 3. Extract Balance Sheet (Instant Context)
        bs_data = _extract_balance_sheet(facts_df)
        if not bs_data:
            logger.warning(f"Failed to extract balance sheet for {ticker}")
            return None
        
        # 4. Extract Income Statement (Duration Context)
        is_data = _extract_income_statement(facts_df)
        if not is_data:
            logger.warning(f"Failed to extract income statement for {ticker}")
            return None
        
        # 5. Extract Cash Flow Statement (Duration Context)
        cf_data = _extract_cash_flow_statement(facts_df)
        if not cf_data:
            logger.warning(f"Failed to extract cash flow statement for {ticker}")
            return None
        
        # 6. Create Financial Health Report
        report = FinancialHealthReport(
            company_ticker=ticker,
            fiscal_period=str(filing.filing_date.year),
            bs=bs_data,
            is_=is_data,
            cf=cf_data
        )
        
        return report
        
    except Exception as e:
        logger.error(f"Error fetching financial data for {ticker}: {e}")
        return None


def _get_fact_value_from_df(df: pd.DataFrame, tags: Union[str, List[str]], context_type: str = 'instant', default: Optional[float] = None) -> Optional[float]:
    """
    Helper to extract value from facts dataframe.
    
    Args:
        df: The facts dataframe
        tags: Single tag or list of tags (waterfall)
        context_type: 'instant' or 'duration'
        default: Default value if not found
    """
    if isinstance(tags, str):
        tags = [tags]
        
    # Filter for consolidated data (where all dim_ columns are NaN)
    dim_cols = [c for c in df.columns if c.startswith('dim_')]
    if dim_cols:
        consolidated_mask = df[dim_cols].isna().all(axis=1)
        clean_df = df[consolidated_mask]
    else:
        clean_df = df

    sort_col = 'period_instant' if context_type == 'instant' and 'period_instant' in df.columns else 'period_end'
    
    for tag in tags:
        try:
            # Filter by tag
            result = clean_df[clean_df['concept'] == tag]
            if result.empty:
                continue
                
            # Sort by date descending to get most recent
            if sort_col in result.columns:
                result = result.sort_values(by=sort_col, ascending=False)
            
            # Get value
            val = result.iloc[0]['value']
            # Convert to float (handle strings if any)
            return float(val)
        except Exception:
            continue
            
    return default


def _extract_balance_sheet(df: pd.DataFrame) -> Optional[BalanceSheet]:
    """Extract balance sheet data using dataframe logic."""
    try:
        # Determine period date
        period_date = date.today()
        assets_tag = "us-gaap:Assets"
        
        # Try to find the date from the Assets tag
        assets_rows = df[df['concept'] == assets_tag]
        if not assets_rows.empty and 'period_instant' in df.columns:
            # Sort desc and take top
            assets_rows = assets_rows.sort_values(by='period_instant', ascending=False)
            latest_date_str = assets_rows.iloc[0]['period_instant']
            if latest_date_str:
                # Handle string date conversion if needed, assuming edgartools returns usable format or string
                if isinstance(latest_date_str, str):
                    period_date = datetime.strptime(latest_date_str, "%Y-%m-%d").date()
                else:
                    period_date = latest_date_str
        
        get_val = lambda t, d=None: _get_fact_value_from_df(df, t, 'instant', d)
        
        bs = BalanceSheet(
            period_date=period_date,
            assets_current=get_val("us-gaap:AssetsCurrent"),
            liabilities_current=get_val("us-gaap:LiabilitiesCurrent"),
            cash_and_equivalents=get_val(
                ["us-gaap:CashAndCashEquivalentsAtCarryingValue", "us-gaap:Cash", "us-gaap:CashEquivalentsAtCarryingValue"]
            ),
            receivables_net=get_val(
                ["us-gaap:ReceivablesNetCurrent", "us-gaap:AccountsReceivableNetCurrent"]
            ),
            inventory=get_val(["us-gaap:InventoryNet", "us-gaap:InventoryGross"]),
            marketable_securities=get_val(
                ["us-gaap:MarketableSecuritiesCurrent", "us-gaap:AvailableForSaleSecuritiesCurrent"]
            ),
            total_assets=get_val("us-gaap:Assets"),
            total_liabilities=get_val("us-gaap:Liabilities"),
            total_equity=get_val(
                ["us-gaap:StockholdersEquity", "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
            ),
            debt_current=get_val(["us-gaap:DebtCurrent", "us-gaap:ShortTermBorrowings"]),
            debt_noncurrent=get_val(["us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermDebt"]),
            accounts_payable=get_val(["us-gaap:AccountsPayableCurrent", "us-gaap:AccountsPayableAndAccruedLiabilitiesCurrent"])
        )
        return bs
    except Exception as e:
        logger.error(f"Error extracting balance sheet: {e}")
        return None


def _extract_income_statement(df: pd.DataFrame) -> Optional[IncomeStatement]:
    try:
        # Determine period dates (rough approximation from Revenue)
        period_start = date.today().replace(month=1, day=1)
        period_end = date.today()
        
        get_val = lambda t, d=None: _get_fact_value_from_df(df, t, 'duration', d)

        is_ = IncomeStatement(
            period_start=period_start,
            period_end=period_end,
            revenue=get_val(["us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"]),
            cogs=get_val(["us-gaap:CostOfGoodsAndServicesSold", "us-gaap:CostOfRevenue"]),
            gross_profit=get_val("us-gaap:GrossProfit", d=None),
            operating_expenses=get_val("us-gaap:OperatingExpenses"),
            operating_income=get_val("us-gaap:OperatingIncomeLoss"),
            net_income=get_val(["us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss"]),
            interest_expense=get_val("us-gaap:InterestExpense"),
            tax_expense=get_val("us-gaap:IncomeTaxExpenseBenefit"),
            depreciation_amortization=get_val("us-gaap:DepreciationDepletionAndAmortization")
        )
        return is_
    except Exception as e:
        logger.error(f"Error extracting income statement: {e}")
        return None


def _extract_cash_flow_statement(df: pd.DataFrame) -> Optional[CashFlowStatement]:
    try:
        period_start = date.today().replace(month=1, day=1)
        period_end = date.today()
        
        get_val = lambda t, d=None: _get_fact_value_from_df(df, t, 'duration', d)

        cf = CashFlowStatement(
            period_start=period_start,
            period_end=period_end,
            ocf=get_val("us-gaap:NetCashProvidedByUsedInOperatingActivities"),
            capex=get_val(["us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", "us-gaap:PaymentsToAcquireProductiveAssets"]),
            dividends_paid=get_val(["us-gaap:PaymentsOfDividends", "us-gaap:PaymentsOfDividendsCommonStock"])
        )
        return cf
    except Exception as e:
        logger.error(f"Error extracting cash flow statement: {e}")
        return None
