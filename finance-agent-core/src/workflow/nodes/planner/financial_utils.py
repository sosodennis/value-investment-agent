import logging
import re
import pandas as pd
from typing import Optional, List, Union, Dict, Any
from datetime import date, datetime
from edgar import Company, set_identity

from .financial_models import (
    # Balance Sheet Models
    BalanceSheetBase,
    CorporateBalanceSheet,
    BankBalanceSheet,
    REITBalanceSheet,
    BalanceSheetVariant,
    TraceableField,
    
    # Income Statement Models
    IncomeStatementBase,
    CorporateIncomeStatement,
    BankIncomeStatement,
    REITIncomeStatement,
    IncomeStatementVariant,
    
    # Cash Flow Models
    CashFlowStatementBase,
    CorporateCashFlow,
    REITCashFlow,
    CashFlowStatementVariant,
    
    # Aggregate Report
    FinancialHealthReport,
    IndustryType
)

logger = logging.getLogger(__name__)

# Set SEC EDGAR identity
set_identity("ValueInvestmentAgent research@example.com")


def _determine_industry_type(sic_code: Optional[int]) -> IndustryType:
    """
    Determine industry type based on SIC code.
    
    SIC Code Ranges:
    - 6000-6299: Banking & Financial Institutions
    - 6798: Real Estate Investment Trusts (REITs)
    - Others: Corporate (default)
    """
    if sic_code is None:
        return IndustryType.CORPORATE
    
    if 6000 <= sic_code <= 6299:
        return IndustryType.BANK
    elif sic_code == 6798:
        return IndustryType.REIT
    else:
        return IndustryType.CORPORATE


def _df_to_dict(df: pd.DataFrame) -> Dict[str, float]:
    """
    Helper: Converts a Clean Consolidated DataFrame to a dictionary for simple field initialization.
    Takes the maximum absolute value for each concept to handle duplicates in the main stream.
    """
    data = {}
    if df.empty or 'concept' not in df.columns or 'value' not in df.columns:
        return data
    
    # De-duplicate by taking the largest absolute value for each concept (typical for financial reports)
    for concept, group in df.groupby('concept'):
        # Filter for rows with numeric values to avoid idxmax() on NaNs
        numeric_group = group.dropna(subset=['value'])
        if not numeric_group.empty:
            best_idx = numeric_group['value'].abs().idxmax()
            data[str(concept)] = float(numeric_group.loc[best_idx, 'value'])
    return data


def _filter_consolidated_strict(df: pd.DataFrame, target_date_str: str = None) -> pd.DataFrame:
    """
    Main Stream Filter (Strict):
    1. Removes Dimension columns (keeping only Consolidated).
    2. STRICT Date Matching (Drops NaT).
    """
    # 1. Dimension Filter
    dim_cols = [c for c in df.columns if c.startswith('dim')]
    if dim_cols:
        # Keep only rows where all dimensions are NaN (Consolidated)
        mask_cons = df[dim_cols].isna().all(axis=1)
        clean_df = df[mask_cons].copy()
    else:
        clean_df = df.copy()

    # 2. Strict Date Filter (if target date provided)
    if target_date_str:
        try:
            target_dt = pd.to_datetime(target_date_str)
            date_buffer = pd.Timedelta(days=7)
            
            # Must have date AND be within range (NaT is excluded here)
            mask_date = (clean_df['filter_date_dt'] >= (target_dt - date_buffer)) & \
                        (clean_df['filter_date_dt'] <= (target_dt + date_buffer))
            clean_df = clean_df[mask_date].copy()
        except Exception:
            pass # Keep as is if date parsing fails
            
    return clean_df


def fetch_financial_data(ticker: str, years: int = 3) -> List[FinancialHealthReport]:
    """
    Fetch financial data using Dual-Stream Architecture.
    
    Architecture:
    - Stream 1 (Deep): Keeps NaT and Dimensions using 'Negative Filtering' (keeps everything except explicitly old data).
    - Stream 2 (Main): Strict Consolidated Filtering for standard fields.
    """
    reports = []
    logger.info(f"Fetching financial data for {ticker} (Last {years} years)...")
    
    try:
        set_identity("ValueInvestmentAgent research@example.com")
        company = Company(ticker)
        filings = company.get_filings(form="10-K", amendments=False).latest(years + 2)
        
        if not filings:
            logger.warning(f"No 10-K filings found for {ticker}")
            return []
            
        count = 0
        for filing in filings:
            if count >= years:
                break
                
            try:
                logger.info(f"Processing 10-K filing filed on: {filing.filing_date}")
                xbrl = filing.xbrl()
                if not xbrl: continue

                try:
                    raw_df = xbrl.facts.to_dataframe()
                except Exception as e:
                    logger.error(f"Failed to convert facts to dataframe: {e}")
                    continue

                # --- 1. Standardization (Clean Slate) ---
                clean_data = {}
                
                # A. Concept Extraction
                if 'concept' in raw_df.columns: clean_data['concept'] = raw_df['concept']
                elif 'fact' in raw_df.columns: clean_data['concept'] = raw_df['fact']
                elif 'tag' in raw_df.columns: clean_data['concept'] = raw_df['tag']
                elif 'label' in raw_df.columns: clean_data['concept'] = raw_df['label']
                else: continue

                # B. Value Extraction (Numeric)
                if 'numeric_value' in raw_df.columns:
                    clean_data['value'] = pd.to_numeric(raw_df['numeric_value'], errors='coerce')
                elif 'value' in raw_df.columns:
                    clean_data['value'] = pd.to_numeric(raw_df['value'], errors='coerce')
                else:
                    clean_data['value'] = pd.Series([0.0] * len(raw_df))

                # C. Value Raw Extraction (Text - CRITICAL for Dates/Metadata)
                if 'value' in raw_df.columns:
                    clean_data['value_raw'] = raw_df['value']
                elif 'val' in raw_df.columns:
                    clean_data['value_raw'] = raw_df['val']
                elif 'numeric_value' in raw_df.columns:
                    clean_data['value_raw'] = raw_df['numeric_value']
                else:
                    clean_data['value_raw'] = pd.Series([""] * len(raw_df))

                # D. Date Normalization
                end_col = next((c for c in ['end_date', 'period_end', 'period.end'] if c in raw_df.columns), None)
                inst_col = next((c for c in ['date', 'period_instant', 'instant'] if c in raw_df.columns), None)
                clean_data['end_date'] = raw_df[end_col] if end_col else pd.Series([pd.NaT] * len(raw_df))
                clean_data['date'] = raw_df[inst_col] if inst_col else pd.Series([pd.NaT] * len(raw_df))

                # E. Dimension preservation
                dim_cols = [c for c in raw_df.columns if c.startswith('dim')]
                for dim in dim_cols:
                    clean_data[dim] = raw_df[dim]

                processed_df = pd.DataFrame(clean_data)
                processed_df['filter_date'] = processed_df['end_date'].combine_first(processed_df['date'])
                processed_df['filter_date_dt'] = pd.to_datetime(processed_df['filter_date'], errors='coerce')

                # --- 2. Context Locking ---
                fiscal_year = str(filing.filing_date.year - 1)
                fy_rows = processed_df[processed_df['concept'] == 'dei:DocumentFiscalYearFocus']
                if not fy_rows.empty: fiscal_year = str(fy_rows.iloc[0]['value_raw'])
                
                target_period_end = None
                ed_rows = processed_df[processed_df['concept'] == 'dei:DocumentPeriodEndDate']
                if not ed_rows.empty:
                    dt_obj = pd.to_datetime(ed_rows.iloc[0]['value_raw'], errors='coerce')
                    if pd.notna(dt_obj): target_period_end = dt_obj.strftime('%Y-%m-%d')

                if not target_period_end:
                    logger.warning(f"❌ Target period end date not found for filing on {filing.filing_date}")
                    continue
                logger.info(f"🔒 Context Locked: FY{fiscal_year} ending on {target_period_end}")

                # --- 3. Deep Stream Preparation (Negative Filtering) ---
                # Strategy: Keep everything EXCEPT explicitly old data.
                target_dt = pd.to_datetime(target_period_end)
                cutoff_date = target_dt - pd.Timedelta(days=90) # Data older than 3 months is likely from previous year
                
                # Filter Logic: Keep if (Date >= Cutoff) OR (Date is NaT)
                is_old = (processed_df['filter_date_dt'] < cutoff_date)
                deep_stream_df = processed_df[~is_old].copy()
                
                logger.debug(f"Deep Stream size: {len(deep_stream_df)} (Original: {len(processed_df)})")
                
                if len(deep_stream_df) < 10:
                    logger.warning(f"⚠️ Deep Stream too small ({len(deep_stream_df)}) for {ticker}")
                    continue

                # Industry detection
                sic_code = None
                try:
                    if hasattr(company, 'sic'): sic_code = int(company.sic)
                    if sic_code is None:
                        sic_rows = deep_stream_df[deep_stream_df['concept'] == 'dei:EntityStandardIndustrialClassification']
                        if not sic_rows.empty: sic_code = int(float(sic_rows.iloc[0]['value_raw']))
                except Exception as e:
                    logger.debug(f"SIC Detection failed: {e}")

                industry_type = _determine_industry_type(sic_code)
                
                logger.info(f"Industry: {industry_type} (SIC: {sic_code})")

                # --- 4. Factory Injection ---
                bs_data = _extract_balance_sheet_factory(deep_stream_df, industry_type, target_period_end)
                is_data = _extract_income_statement_factory(deep_stream_df, industry_type, bs_data, target_period_end)
                cf_data = _extract_cash_flow_factory(deep_stream_df, industry_type, target_period_end)

                if bs_data and is_data and cf_data:
                    reports.append(FinancialHealthReport(
                        company_ticker=ticker, fiscal_period=fiscal_year,
                        bs=bs_data, is_=is_data, cf=cf_data
                    ))
                    count += 1
                    logger.info(f"✅ Created report for FY{fiscal_year}")
                else:
                    missing = []
                    if not bs_data: missing.append("BS")
                    if not is_data: missing.append("IS")
                    if not cf_data: missing.append("CF")
                    logger.warning(f"⚠️ Incomplete statements for {ticker}: Missing {', '.join(missing)}")

            except Exception as e:
                logger.error(f"Error processing filing: {e}", exc_info=True)
                continue
        
    except Exception as e:
        logger.error(f"Global error: {e}")
        
    return reports


def _extract_balance_sheet_factory(df: pd.DataFrame, industry: IndustryType, target_date_str: str) -> Optional[BalanceSheetVariant]:
    """Factory implementing Dual-Stream Injection."""
    if df.empty: return None
    
    # Stream 2: Main Stream (Clean, Consolidated, Strict Date)
    clean_df = _filter_consolidated_strict(df, target_date_str)
    standardized_dict = _df_to_dict(clean_df)
    
    # Inject both standardized dict and the full deep stream DF
    standardized_dict['deep_stream_df'] = df 
    
    try:
        period_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    except:
        period_date = date.today()

    if industry == IndustryType.BANK:
        return BankBalanceSheet(industry=IndustryType.BANK, period_date=period_date, **standardized_dict)
    elif industry == IndustryType.REIT:
        return REITBalanceSheet(industry=IndustryType.REIT, period_date=period_date, **standardized_dict)
    else:
        return CorporateBalanceSheet(industry=IndustryType.CORPORATE, period_date=period_date, **standardized_dict)


def _extract_income_statement_factory(df: pd.DataFrame, industry: IndustryType, bs: BalanceSheetVariant, target_date_str: str) -> Optional[IncomeStatementVariant]:
    if df.empty: return None
    
    clean_df = _filter_consolidated_strict(df, target_date_str)
    standardized_dict = _df_to_dict(clean_df)
    standardized_dict['deep_stream_df'] = df
    
    try:
        end_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        start_date = end_date.replace(year=end_date.year - 1) + pd.Timedelta(days=1)
    except:
        end_date, start_date = date.today(), date.today()

    if industry == IndustryType.BANK:
        avg_assets = bs.total_assets.value if bs and hasattr(bs, 'total_assets') else None
        return BankIncomeStatement(
            industry=IndustryType.BANK, period_start=start_date, period_end=end_date,
            avg_earning_assets=TraceableField(value=avg_assets, source_tags=['Calculated from BS'], is_calculated=True, formula_logic='Approximated from Total Assets'),
            **standardized_dict
        )
    elif industry == IndustryType.REIT:
        return REITIncomeStatement(industry=IndustryType.REIT, period_start=start_date, period_end=end_date, **standardized_dict)
    else:
        return CorporateIncomeStatement(industry=IndustryType.CORPORATE, period_start=start_date, period_end=end_date, **standardized_dict)


def _extract_cash_flow_factory(df: pd.DataFrame, industry: IndustryType, target_date_str: str) -> Optional[CashFlowStatementVariant]:
    if df.empty: return None
    
    clean_df = _filter_consolidated_strict(df, target_date_str)
    standardized_dict = _df_to_dict(clean_df)
    standardized_dict['deep_stream_df'] = df
    
    try:
        end_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        start_date = end_date.replace(year=end_date.year - 1) + pd.Timedelta(days=1)
    except:
        end_date, start_date = date.today(), date.today()

    if industry == IndustryType.REIT:
        return REITCashFlow(industry=IndustryType.REIT, period_start=start_date, period_end=end_date, **standardized_dict)
    else:
        return CorporateCashFlow(industry=IndustryType.CORPORATE, period_start=start_date, period_end=end_date, **standardized_dict)



# End of file
