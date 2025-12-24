import logging
import re
import pandas as pd
from typing import Optional, List, Union
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


def fetch_financial_data(ticker: str, years: int = 3) -> List[FinancialHealthReport]:
    """
    Fetch financial data with Clean Slate Extraction to prevent column name collisions.
    
    Architecture:
    1. Reconstruction: Build a fresh facts_df with dual value columns (Value + ValueRaw).
    2. Dual-Value Preservation: 'value' (numeric) for logic, 'value_raw' (text) for metadata.
    3. NaT Defense: Handle missing dates and string conversions gracefully.
    4. Context Locking: Filter to the correct fiscal year using fuzzy date windows.
    """
    reports = []
    logger.info(f"Fetching financial data for {ticker} (Last {years} years)...")
    
    try:
        set_identity("ValueInvestmentAgent research@example.com")
        company = Company(ticker)
        
        # Get 10-K filings (sorted by date descending)
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
                
                # 1. Parse XBRL
                xbrl = filing.xbrl()
                if not xbrl: continue

                # 2. Convert to raw DataFrame
                try:
                    raw_df = xbrl.facts.to_dataframe()
                except Exception as e:
                    logger.error(f"Failed to convert facts to dataframe: {e}")
                    continue

                # =================================================================
                # 🏗️ RECONSTRUCTION: Clean Slate Strategy V2 (Dual-Value)
                # =================================================================
                # We build a fresh DataFrame from the ground up to avoid duplicate 
                # column name errors and preserve both numeric and string values.
                
                clean_data = {}
                
                # A. Extract Concept (XBRL Tag)
                # Priority: concept > fact > tag > label
                if 'concept' in raw_df.columns: clean_data['concept'] = raw_df['concept']
                elif 'fact' in raw_df.columns: clean_data['concept'] = raw_df['fact']
                elif 'tag' in raw_df.columns: clean_data['concept'] = raw_df['tag']
                elif 'label' in raw_df.columns: clean_data['concept'] = raw_df['label']
                else:
                    logger.error("Critical: No concept/fact column found in raw xbrl.")
                    continue

                # B. Extract Value (Numeric Version - for calculations)
                # Priority: numeric_value > value > val
                if 'numeric_value' in raw_df.columns: 
                    clean_data['value'] = raw_df['numeric_value']
                elif 'value' in raw_df.columns: 
                    clean_data['value'] = pd.to_numeric(raw_df['value'], errors='coerce')
                elif 'val' in raw_df.columns:
                    clean_data['value'] = pd.to_numeric(raw_df['val'], errors='coerce')
                else:
                    clean_data['value'] = pd.Series([0.0] * len(raw_df))

                # C. Extract Value Raw (Text Version - for metadata extraction)
                # Ensures date strings like "2024-06-30" aren't lost to numeric coercion.
                if 'value' in raw_df.columns:
                    clean_data['value_raw'] = raw_df['value']
                elif 'val' in raw_df.columns:
                    clean_data['value_raw'] = raw_df['val']
                else:
                    clean_data['value_raw'] = clean_data['value']

                # D. Extract Dates (end_date for Duration, date for Instant)
                # Normalize varied column names from different parsers
                if 'end_date' in raw_df.columns: clean_data['end_date'] = raw_df['end_date']
                elif 'period_end' in raw_df.columns: clean_data['end_date'] = raw_df['period_end']
                elif 'period.end' in raw_df.columns: clean_data['end_date'] = raw_df['period.end']
                else: clean_data['end_date'] = pd.Series([pd.NaT] * len(raw_df))

                if 'date' in raw_df.columns: clean_data['date'] = raw_df['date']
                elif 'period_instant' in raw_df.columns: clean_data['date'] = raw_df['period_instant']
                elif 'instant' in raw_df.columns: clean_data['date'] = raw_df['instant']
                else: clean_data['date'] = pd.Series([pd.NaT] * len(raw_df))

                # E. Extract Dimensions (Crucial for filtering consolidated data)
                # This fixes the Microsoft Revenue mismatch by allowing us to filter out segments.
                dim_cols = [c for c in raw_df.columns if c.startswith('dim')]
                for dim in dim_cols:
                    clean_data[dim] = raw_df[dim]

                # Build the cleaned, unique-column DataFrame
                facts_df = pd.DataFrame(clean_data)
                
                # =================================================================
                # 🔒 CONTEXT LOCKING: Metadata Extraction from value_raw
                # =================================================================
                
                # Extract Fiscal Year (Use value_raw to avoid NaN)
                fiscal_year = None
                fy_rows = facts_df[facts_df['concept'] == 'dei:DocumentFiscalYearFocus']
                if not fy_rows.empty:
                    fiscal_year = str(fy_rows.iloc[0]['value_raw'])
                else:
                    fiscal_year = str(filing.filing_date.year - 1)
                
                # Extract Target Period End Date (Use value_raw to avoid NaN)
                target_period_end = None
                end_date_rows = facts_df[facts_df['concept'] == 'dei:DocumentPeriodEndDate']
                
                if not end_date_rows.empty:
                    raw_date_val = end_date_rows.iloc[0]['value_raw']
                    dt_obj = pd.to_datetime(raw_date_val, errors='coerce')
                    
                    if pd.notna(dt_obj):
                        target_period_end = dt_obj.strftime('%Y-%m-%d')
                    else:
                        logger.error(f"Target date parsed as NaT for value: {raw_date_val}")
                
                if not target_period_end:
                    logger.warning(f"Skipping FY{fiscal_year}: No valid PeriodEndDate found.")
                    continue
                
                logger.info(f"🔒 Context Locked: FY{fiscal_year} ending on {target_period_end}")

                # =================================================================
                # 📅 FUZZY FILTER: +/- 7 Days Window
                # =================================================================
                
                target_dt = pd.to_datetime(target_period_end)
                
                # Merge date sources
                facts_df['filter_date'] = facts_df['end_date'].combine_first(facts_df['date'])
                facts_df['filter_date_dt'] = pd.to_datetime(facts_df['filter_date'], errors='coerce')
                
                # Match within 7 days to catch Fri/Sun alignment issues
                date_buffer = pd.Timedelta(days=7)
                mask = (facts_df['filter_date_dt'] >= (target_dt - date_buffer)) & \
                       (facts_df['filter_date_dt'] <= (target_dt + date_buffer))
                
                current_period_df = facts_df[mask].copy()
                
                # Ensure we have data (Using numeric value for calculation checks)
                has_assets = current_period_df[
                    current_period_df['concept'].str.contains('Assets', case=False, na=False) & 
                    current_period_df['value'].notna()
                ].any().any()
                
                if not has_assets and len(current_period_df) <= 10:
                    logger.warning(f"⚠️ Insufficient data for FY{fiscal_year} in 7-day window.")
                    continue

                logger.info(f"✅ Data Locked: Found {len(current_period_df)} facts for FY{fiscal_year}")

                # =================================================================
                # INDUSTRY & EXTRACTION
                # =================================================================
                
                # Extract SIC code for industry detection (Use value_raw as SIC may be string)
                sic_code = None
                try:
                    if hasattr(company, 'sic'):
                        sic_code = int(company.sic) if company.sic else None
                    
                    if sic_code is None:
                        sic_rows = current_period_df[current_period_df['concept'] == 'dei:EntityStandardIndustrialClassification']
                        if not sic_rows.empty:
                            sic_code = sic_rows.iloc[0]['value_raw']
                except Exception as e:
                    logger.warning(f"SIC extraction failed: {e}")
                
                industry_type = _determine_industry_type(sic_code)
                logger.info(f"Industry type: {industry_type.value} (SIC: {sic_code})")

                # Extract Statements (Passing target_period_end to prevent hardcoded 'today')
                bs_data = _extract_balance_sheet_factory(current_period_df, industry_type, target_period_end)
                is_data = _extract_income_statement_factory(current_period_df, industry_type, bs_data, target_period_end)
                cf_data = _extract_cash_flow_factory(current_period_df, industry_type, target_period_end)

                # Create Report
                if bs_data and is_data and cf_data:
                    report = FinancialHealthReport(
                        company_ticker=ticker,
                        fiscal_period=fiscal_year,
                        bs=bs_data,
                        is_=is_data,
                        cf=cf_data
                    )
                    reports.append(report)
                    count += 1
                    logger.info(f"✅ Created report for FY{fiscal_year}")
                else:
                    logger.warning(f"Failed to create complete report for FY{fiscal_year}")

            except Exception as e:
                logger.error(f"Error processing filing {filing.filing_date}: {e}")
                continue
        
    except Exception as e:
        logger.error(f"Global error fetching data for {ticker}: {e}")
        
    return reports

def _filter_consolidated(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter out segment/departmental data (dimensions) to keep only consolidated totals.
    Microsoft Fix: Segment revenue is filtered out, leaving only the corporate total.
    """
    dim_cols = [c for c in df.columns if c.startswith('dim')]
    if not dim_cols:
        return df
        
    # Consolidated rows have NaN in all dimension columns
    mask = df[dim_cols].isna().all(axis=1)
    
    # Safety: If mask removes everything, fallback to original
    if mask.sum() == 0:
        return df
        
    return df[mask].copy()


def _get_fact_value_from_df(df: pd.DataFrame, tags: Union[str, List[str]], context_type: str = 'instant', default: Optional[float] = None, apply_filter: bool = True) -> Optional[float]:
    """
    Helper to extract value from facts dataframe.
    """
    if isinstance(tags, str):
        tags = [tags]
        
    # Apply consolidated filter by default
    clean_df = _filter_consolidated(df) if apply_filter else df

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


def _get_fact_smart(df: pd.DataFrame, 
                    standard_tags: List[str], 
                    fuzzy_keywords: List[str], 
                    exclude_keywords: List[str] = None) -> Optional[float]:
    """
    Intelligent extractor: Tries standard tags first, then fuzzy matches extension tags.
    """
    # 1. Standard Fallback (Most precise)
    val = _get_fact_value_from_df(df, standard_tags)
    if val is not None:
        return val

    # 2. Fuzzy Match (for extension tags like epr:Depreciation...)
    if not fuzzy_keywords:
        return None

    # Filter for extension tags (exclude standard namespaces)
    # Typically extension tags do not contain 'us-gaap' or 'dei'
    # Check if 'concept' column exists
    if 'concept' not in df.columns:
        return None
        
    # [FIX] Do NOT filter 'us-gaap'! We want to find standard tags too if fuzzy matches.
    # Only filter out 'dei' (Document and Entity Information) which are metadata.
    search_pool = df[~df['concept'].astype(str).str.contains('dei:', case=False, na=False)]
    
    # Construct Regex: Must contain ALL fuzzy_keywords
    # Lookahead pattern: (?=.*Keyword1)(?=.*Keyword2)
    pattern = "".join([f"(?=.*{k})" for k in fuzzy_keywords])
    
    matches = []
    # Optimization: Search unique concepts to avoid loop overhead
    unique_concepts = search_pool['concept'].unique()
    
    for concept in unique_concepts:
        concept_str = str(concept)
        # Check matching
        if re.search(pattern, concept_str, re.IGNORECASE):
            # Check exclusions
            if exclude_keywords and any(ex.lower() in concept_str.lower() for ex in exclude_keywords):
                continue
            matches.append(concept_str)

    if not matches:
        return None

    # Priority Strategy: Prefer tags that are SHORTER (usually the parent concept) 
    matches.sort(key=len) # Sort by length, shortest first
    
    best_guess_tag = matches[0]
    # logger.warning(f"⚠️ Fuzzy Match Found: Used '{best_guess_tag}' for keywords {fuzzy_keywords}")
    
    return _get_fact_value_from_df(df, best_guess_tag)


def _extract_balance_sheet_factory(df: pd.DataFrame, industry: IndustryType, target_date_str: str) -> Optional[BalanceSheetVariant]:
    """Factory to extract industry-specific balance sheet with accurate date"""
    try:
        period_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    except:
        period_date = date.today()

    # Filter for consolidated data
    clean_df = _filter_consolidated(df)

    if industry == IndustryType.BANK:
        return BankBalanceSheet(industry=IndustryType.BANK, period_date=period_date, _raw_df=clean_df)
    elif industry == IndustryType.REIT:
        return REITBalanceSheet(industry=IndustryType.REIT, period_date=period_date, _raw_df=clean_df)
    else:
        return CorporateBalanceSheet(industry=IndustryType.CORPORATE, period_date=period_date, _raw_df=clean_df)


def _extract_income_statement_factory(df: pd.DataFrame, industry: IndustryType, bs: BalanceSheetVariant, target_date_str: str) -> Optional[IncomeStatementVariant]:
    """Factory to extract industry-specific income statement with accurate dates"""
    try:
        end_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        # Simple heuristic for start date (1 year before)
        start_date = end_date.replace(year=end_date.year - 1) + pd.Timedelta(days=1)
    except:
        end_date = date.today()
        start_date = date.today()

    clean_df = _filter_consolidated(df)

    if industry == IndustryType.BANK:
        # Calculate average earning assets (approximation using total assets from BS)
        # NIM calculation depends on this.
        avg_assets = bs.total_assets.value if bs and hasattr(bs, 'total_assets') else None
        
        return BankIncomeStatement(
            industry=IndustryType.BANK, 
            period_start=start_date, 
            period_end=end_date,
            avg_earning_assets=TraceableField(
                value=avg_assets,
                source_tags=['Calculated from BS'],
                is_calculated=True,
                formula_logic='Approximated from Total Assets'
            ),
            _raw_df=clean_df
        )
    elif industry == IndustryType.REIT:
        return REITIncomeStatement(industry=IndustryType.REIT, period_start=start_date, period_end=end_date, _raw_df=clean_df)
    else:
        return CorporateIncomeStatement(industry=IndustryType.CORPORATE, period_start=start_date, period_end=end_date, _raw_df=clean_df)


def _extract_cash_flow_factory(df: pd.DataFrame, industry: IndustryType, target_date_str: str) -> Optional[CashFlowStatementVariant]:
    """Factory to extract industry-specific cash flow statement with accurate dates"""
    try:
        end_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        start_date = end_date.replace(year=end_date.year - 1) + pd.Timedelta(days=1)
    except:
        end_date = date.today()
        start_date = date.today()

    clean_df = _filter_consolidated(df)

    if industry == IndustryType.REIT:
        return REITCashFlow(industry=IndustryType.REIT, period_start=start_date, period_end=end_date, _raw_df=clean_df)
    else:
        return CorporateCashFlow(industry=IndustryType.CORPORATE, period_start=start_date, period_end=end_date, _raw_df=clean_df)



# End of file
