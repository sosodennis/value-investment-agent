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
    Fetch financial data from SEC EDGAR using edgartools.
    Returns a list of reports for the last N years (or matching filings found).
    """
    reports = []
    try:
        logger.info(f"Fetching financial data for {ticker} (Last {years} years)...")
        
        # 1. Get company and latest 10-K filings (excluding amendments)
        logger.debug(f"Getting filings for {ticker}...")
        company = Company(ticker)
        filings = company.get_filings(form="10-K", amendments=False)
        
        if not filings:
            logger.warning(f"No 10-K filings found for {ticker}")
            return []
            
        # Refactor: Iterate safely instead of slicing/len() on potentially fragile Filings object
        count = 0
        for i, filing in enumerate(filings):
            if count >= years:
                break
                
            try:
                # Try to get date safely
                f_date = "Unknown Date"
                try:
                    f_date = str(filing.filing_date)
                except Exception as e:
                    logger.warning(f"Could not read filing date via filing.filing_date: {e}")
                    
                logger.info(f"Processing 10-K filing {i+1}: {f_date}")
                
                # 2. Extract XBRL data as Dataframe
                xbrl = filing.xbrl()
                if not xbrl:
                    logger.warning(f"No XBRL data available for filing {filing.filing_date}")
                    continue
                    
                try:
                    facts_df = xbrl.facts.to_dataframe()
                except Exception as e:
                    logger.error(f"Failed to convert facts to dataframe for filing {filing.filing_date}: {e}")
                    continue
                
                # 3. Determine Industry Type from SIC Code
                sic_code = None
                try:
                    # Primary: Get SIC from company object
                    if hasattr(company, 'sic'):
                        sic_code = int(company.sic) if company.sic else None
                    
                    # Fallback: Try to extract from XBRL facts
                    if sic_code is None:
                        # Try dei:EntityStandardIndustrialClassification
                        sic_rows = facts_df[facts_df['concept'] == 'dei:EntityStandardIndustrialClassification']
                        if not sic_rows.empty:
                            sic_value = sic_rows.iloc[0]['value']
                            sic_code = int(sic_value) if sic_value else None
                except Exception as e:
                    logger.warning(f"Could not extract SIC code: {e}")
                
                industry_type = _determine_industry_type(sic_code)
                logger.info(f"Determined industry type: {industry_type.value} (SIC: {sic_code})")

                # 4. Extract Balance Sheet (using factory)
                bs_data = _extract_balance_sheet_factory(facts_df, industry_type)
                if not bs_data:
                    logger.warning(f"Failed to extract balance sheet for {filing.filing_date}")
                    continue
                
                # 5. Extract Income Statement (using factory)
                is_data = _extract_income_statement_factory(facts_df, industry_type, bs_data)
                if not is_data:
                    logger.warning(f"Failed to extract income statement for {filing.filing_date}")
                    continue
                
                # 6. Extract Cash Flow Statement (using factory)
                cf_data = _extract_cash_flow_factory(facts_df, industry_type)
                if not cf_data:
                    logger.warning(f"Failed to extract cash flow statement for {filing.filing_date}")
                    continue
                
                # Extract Fiscal Year
                fiscal_year = str(filing.filing_date.year - 1) # Default heuristic (Filing Year - 1)
                try:
                    # Try to get explicit fiscal year from XBRL
                    fy_rows = facts_df[facts_df['concept'] == 'dei:DocumentFiscalYearFocus']
                    if not fy_rows.empty:
                        fiscal_year = str(fy_rows.iloc[0]['value'])
                except Exception as e:
                    logger.warning(f"Could not extract DocumentFiscalYearFocus: {e}")

                # 7. Create Financial Health Report
                report = FinancialHealthReport(
                    company_ticker=ticker,
                    fiscal_period=fiscal_year,
                    bs=bs_data,
                    is_=is_data,
                    cf=cf_data
                )
                reports.append(report)
                count += 1
                
            except Exception as e:
                logger.error(f"Error processing filing {filing.filing_date}: {e}")
                continue
        
    except Exception as e:
        logger.error(f"Error fetching financial data for {ticker}: {e}")
        
    return reports


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


def _extract_balance_sheet_factory(df: pd.DataFrame, industry: IndustryType) -> Optional[BalanceSheetVariant]:
    """Factory to extract industry-specific balance sheet"""
    if industry == IndustryType.BANK:
        return _extract_bank_balance_sheet(df)
    elif industry == IndustryType.REIT:
        return _extract_reit_balance_sheet(df)
    else:
        return _extract_corporate_balance_sheet(df)


def _extract_cash_flow_factory(df: pd.DataFrame, industry: IndustryType) -> Optional[CashFlowStatementVariant]:
    """Factory to extract industry-specific cash flow statement"""
    if industry == IndustryType.REIT:
        return _extract_reit_cash_flow(df)
    else:
        # Bank uses corporate extraction for now (or base)
        return _extract_corporate_cash_flow(df)


def _get_period_date(df: pd.DataFrame) -> date:
    """Helper to determine the balance sheet date"""
    period_date = date.today()
    assets_tag = "us-gaap:Assets"
    assets_rows = df[df['concept'] == assets_tag]
    if not assets_rows.empty and 'period_instant' in df.columns:
        assets_rows = assets_rows.sort_values(by='period_instant', ascending=False)
        latest_date_str = assets_rows.iloc[0]['period_instant']
        if latest_date_str:
            if isinstance(latest_date_str, str):
                try:
                     period_date = datetime.strptime(latest_date_str, "%Y-%m-%d").date()
                except ValueError:
                     period_date = latest_date_str # Fallback
            else:
                 period_date = latest_date_str
    return period_date


def _extract_corporate_balance_sheet(df: pd.DataFrame) -> Optional[CorporateBalanceSheet]:
    """Extract standard corporate balance sheet"""
    try:
        get_val = lambda t, d=None: _get_fact_value_from_df(df, t, 'instant', d)
        period_date = _get_period_date(df)
        
        # 1. Extract Operating Lease Liabilities (MGM / OpCo Logic)
        lease_current = _get_fact_smart(
            df, 
            standard_tags=["us-gaap:OperatingLeaseLiabilityCurrent"],
            fuzzy_keywords=["OperatingLeaseLiability", "Current"],
            exclude_keywords=[]
        )
        
        lease_noncurrent = _get_fact_smart(
            df, 
            standard_tags=["us-gaap:OperatingLeaseLiabilityNoncurrent"],
            fuzzy_keywords=["OperatingLeaseLiability", "Noncurrent"],
            exclude_keywords=[]
        )

        # Fallback Logic: If partials failed, try fetching the Total
        if (lease_current or 0) + (lease_noncurrent or 0) == 0:
            logger.warning("⚠️ MGM Lease Extraction failed! Trying fallback tag 'us-gaap:OperatingLeaseLiability'...")
            lease_total_guess = _get_fact_smart(
                df,
                standard_tags=["us-gaap:OperatingLeaseLiability"],
                fuzzy_keywords=["OperatingLeaseLiability"],
                exclude_keywords=["Current", "Noncurrent"]
            )
            if lease_total_guess and lease_total_guess > 0:
                logger.info(f"✅ Fallback Success: Found Total Lease Liability = {lease_total_guess}")
                # Assign to noncurrent for display purposes
                lease_noncurrent = lease_total_guess
        
        return CorporateBalanceSheet(
            period_date=period_date,
            total_assets=get_val("us-gaap:Assets"),
            total_liabilities=get_val("us-gaap:Liabilities"),
            total_equity=get_val(["us-gaap:StockholdersEquity", "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]),
            cash_and_equivalents=get_val(["us-gaap:CashAndCashEquivalentsAtCarryingValue", "us-gaap:Cash"]),
            marketable_securities=get_val(["us-gaap:MarketableSecuritiesCurrent", "us-gaap:ShortTermInvestments"]),
            # Corporate Specific
            assets_current=get_val("us-gaap:AssetsCurrent"),
            liabilities_current=get_val("us-gaap:LiabilitiesCurrent"),
            receivables_net=get_val(["us-gaap:ReceivablesNetCurrent", "us-gaap:AccountsReceivableNetCurrent"]),
            inventory=get_val("us-gaap:InventoryNet"),
            accounts_payable=get_val("us-gaap:AccountsPayableCurrent"),
            debt_current=get_val(["us-gaap:DebtCurrent", "us-gaap:ShortTermBorrowings", "us-gaap:LongTermDebtCurrent"]),
            debt_noncurrent=get_val(["us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermDebt"]),
            # Adjusted Debt (OpCo Fix)
            lease_liabilities_current=lease_current,
            lease_liabilities_noncurrent=lease_noncurrent,
            
            # Liquidity Fix: Non-Current Marketable Securities (Shadow Cash)
            marketable_securities_noncurrent=get_val([
                "us-gaap:MarketableSecuritiesNoncurrent", 
                "us-gaap:AvailableForSaleSecuritiesNoncurrent",
                "us-gaap:HeldToMaturitySecuritiesNoncurrent",
                "us-gaap:LongTermInvestments"
            ])
        )
    except Exception as e:
        logger.error(f"Error extracting Corporate BS: {e}")
        return None


def _extract_bank_balance_sheet(df: pd.DataFrame) -> Optional[BankBalanceSheet]:
    """Extract bank balance sheet"""
    try:
        get_val = lambda t, d=None: _get_fact_value_from_df(df, t, 'instant', d)
        period_date = _get_period_date(df)
        
        # Cash Calculation (Summation)
        cash_raw = get_val(["us-gaap:CashAndDueFromBanks", "us-gaap:CashAndCashEquivalentsAtCarryingValue", "us-gaap:CashAndCashEquivalents"]) or 0.0
        interest_bearing_deposits = get_val("us-gaap:InterestBearingDepositsInBanks") or 0.0
        total_cash = cash_raw + interest_bearing_deposits

        # Debt Calculation (Summation)
        long_term_debt = get_val(["us-gaap:LongTermDebt", "us-gaap:LongTermDebtAndCapitalLeaseObligations"]) or 0.0
        short_term_debt = get_val("us-gaap:ShortTermBorrowings") or 0.0
        total_debt_calc = long_term_debt + short_term_debt

        return BankBalanceSheet(
            period_date=period_date,
            total_assets=get_val("us-gaap:Assets"),
            total_liabilities=get_val("us-gaap:Liabilities"),
            total_equity=get_val(["us-gaap:StockholdersEquity", "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]),
            cash_and_equivalents=total_cash,
            marketable_securities=get_val(["us-gaap:MarketableSecuritiesCurrent", "us-gaap:AvailableForSaleSecurities"]),
            # Bank Specific
            total_deposits=get_val(["us-gaap:Deposits", "us-gaap:DepositsForeignAndDomestic"]),
            net_loans=get_val(["us-gaap:LoansAndLeasesReceivableNetReportedAmount", "us-gaap:FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss"]),
            total_debt=total_debt_calc
        )
    except Exception as e:
        logger.error(f"Error extracting Bank BS: {e}")
        return None


def _extract_reit_balance_sheet(df: pd.DataFrame) -> Optional[REITBalanceSheet]:
    """Extract REIT balance sheet with Smart Debt Aggregation"""
    try:
        get_val = lambda t, d=None: _get_fact_value_from_df(df, t, 'instant', d)
        period_date = _get_period_date(df)
        
        # --- SMART DEBT EXTRACTION STRATEGY ---
        
        # 1. Standard Aggregates (Try these first)
        standard_debt = get_val([
            "us-gaap:DebtInstrumentCarryingAmount", 
            "us-gaap:LongTermDebtAndCapitalLeaseObligations",
            "us-gaap:LongTermDebt" # Sometimes REITs use this generic tag
        ])

        # 2. Component Aggregation (Sum of parts)
        # We look for specific keywords often used by REITs (Unsecured, Senior Notes, Term Loans, Mortgages)
        
        # Part A: Unsecured / Senior Notes (The biggest chunk for EPR/O)
        # Part A: Unsecured / Senior Notes (The biggest chunk for EPR/O)
        unsecured_val = _get_fact_smart(
            df, 
            standard_tags=["us-gaap:UnsecuredDebt", "us-gaap:SeniorNotes"], 
            # [FIX] Add "Notes" as broader match, but careful with exclusions
            fuzzy_keywords=["SeniorNotes", "Unsecured", "NotesPayable"], 
            exclude_keywords=["Interest", "Expense", "Amortization", "Receivable", "Issuance"]
        ) or 0.0

        # Part B: Mortgages
        mortgages_val = _get_fact_smart(
            df, 
            standard_tags=["us-gaap:MortgageLoansOnRealEstate"], 
            fuzzy_keywords=["Mortgage"], 
            exclude_keywords=["Interest", "Receivable", "Asset"] # Exclude assets
        ) or 0.0

        # Part C: Bank Debt (Term Loans / Credit Lines)
        term_loan_val = _get_fact_smart(
            df, 
            standard_tags=["us-gaap:TermLoan"], 
            fuzzy_keywords=["TermLoan", "CreditFacility", "LineOfCredit", "Revolving"], 
            exclude_keywords=["Interest", "Fee"]
        ) or 0.0

        # Calculate Total Debt (Max of Standard vs Sum-of-Parts)
        # We take the maximum because sometimes the 'Standard' tag might just be one component
        sum_of_parts = unsecured_val + mortgages_val + term_loan_val
        
        # Fallback Logic: If standard debt is suspiciously low (e.g. < 1M), trust sum of parts
        if standard_debt and standard_debt > 1_000_000:
             # If sum of parts is significantly higher (e.g. standard missed Unsecured), take sum of parts
             if sum_of_parts > standard_debt * 1.1: 
                 total_debt_final = sum_of_parts
             else:
                 total_debt_final = standard_debt
        else:
             total_debt_final = sum_of_parts

        # Last Resort Sanity Check: If Debt is still near 0, estimate via Liabilities - Payables
        # (REITs are capital intensive, Debt usually ~50% of Liabilities)
        if total_debt_final < 10_000_000:
            total_liabilities = get_val("us-gaap:Liabilities") or 0.0
            payables = get_val(["us-gaap:AccountsPayableAndAccruedLiabilitiesCurrent", "us-gaap:AccountsPayableCurrent"]) or 0.0
            if total_liabilities > 0:
                 implied_debt = total_liabilities - payables
                 # Only use if implied debt is substantial (e.g. > 100M)
                 if implied_debt > 100_000_000:
                     logger.warning(f"⚠️ Used Implied Debt (Liabilities - AP) for REIT: {total_debt_final}")

        # Ensure the model reflects the calculated total_debt_final
        # Since REITBalanceSheet computes total_debt = unsecured + mortgages + notes,
        # we need to adjust one of these components if total_debt_final > sum of extracted components.
        current_sum = (unsecured_val or 0.0) + (mortgages_val or 0.0) + (term_loan_val or 0.0)
        if total_debt_final > current_sum + 1.0: 
             # Assign difference to unsecured (primary debt for REITs)
             unsecured_val = (unsecured_val or 0.0) + (total_debt_final - current_sum)

        # REIT Specific
        # Asset Logic: Max/Sum of Real Estate Properties (O, EPR) OR Net Investment in Leases (VICI, GLPI)
        re_properties = get_val(["us-gaap:RealEstateInvestmentPropertyNet", "us-gaap:RealEstateRealEstateAssetsNet"]) or 0.0
        
        # --- VICI / Gaming REIT Specific Fix (The "Sum of Buckets" Strategy) ---
        
        # Bucket 1: Sales-Type Leases (Vici's Main Chunk ~30B+)
        stl_current = _get_fact_smart(
            df, [], ["NetInvestmentInLease", "Current"], ["Financing"]
        ) or 0.0
        
        stl_noncurrent = _get_fact_smart(
            df, 
            standard_tags=["us-gaap:NetInvestmentInLeaseSalesTypeLeaseNoncurrent"], 
            fuzzy_keywords=["NetInvestmentInLease", "Noncurrent"],
            exclude_keywords=["Financing"]
        ) or 0.0
        
        # Fallback to Total if NonCurrent missing
        if stl_noncurrent == 0:
             stl_total_guess = _get_fact_smart(
                df, 
                standard_tags=["us-gaap:NetInvestmentInLeaseSalesTypeLease"],
                fuzzy_keywords=["NetInvestmentInLease"],
                exclude_keywords=["Current", "Noncurrent", "Financing"]
             ) or 0.0
             if stl_total_guess > stl_current:
                 sales_type_total = stl_total_guess
             else:
                 sales_type_total = stl_current 
        else:
             sales_type_total = stl_current + stl_noncurrent


        # Bucket 2: Financing Receivables (The missing ~10B+)
        fr_current = _get_fact_smart(
            df, [], ["FinanceLease", "Receivable", "Current"], ["SalesType"]
        ) or 0.0
        
        fr_noncurrent = _get_fact_smart(
            df, 
            standard_tags=["us-gaap:FinanceLeaseReceivablesNoncurrent"],
            fuzzy_keywords=["FinanceLease", "Receivable", "Noncurrent"],
            exclude_keywords=["SalesType"]
        ) or 0.0
        
        # Fallback to Total
        if fr_noncurrent == 0:
             fr_total_guess = _get_fact_smart(
                df,
                standard_tags=["us-gaap:FinanceLeaseReceivables"],
                fuzzy_keywords=["FinanceLease", "Receivable"],
                exclude_keywords=["Current", "Noncurrent", "SalesType"]
             ) or 0.0
             if fr_total_guess > fr_current:
                 financing_total = fr_total_guess
             else:
                 financing_total = fr_current + fr_noncurrent
        else:
             financing_total = fr_current + fr_noncurrent


        # 3. Grand Total
        net_investment_leases = sales_type_total + financing_total

        # --- SAFETY NET (安全網) ---
        # If granular extraction failed (result < 10% of Total Assets), trigger broad search.
        # This handles older years (2022/2023) where tags might be less specific.
        total_assets_val = get_val("us-gaap:Assets") or 0.0
        
        if total_assets_val > 0 and net_investment_leases < (total_assets_val * 0.1):
             logger.warning(f"⚠️ VICI Assets too small ({net_investment_leases:,.0f}). Triggering Safety Net search...")
             
             # Broad Search: "Investment" + "Lease", ignoring SalesType vs Financing distinction
             broad_guess = _get_fact_smart(
                 df, 
                 standard_tags=["us-gaap:NetInvestmentInLeaseSalesTypeLease", "us-gaap:NetInvestmentInLease"],
                 fuzzy_keywords=["Investment", "Lease"], # Broad fuzzy match
                 exclude_keywords=["Current"] # Only exclude explicit current portion
             ) or 0.0
             
             # Use if broad guess provides a better result
             if broad_guess > net_investment_leases:
                 net_investment_leases = broad_guess
                 logger.info(f"✅ Safety Net Applied: Updated Assets to {net_investment_leases:,.0f}")
        # ---------------------------

        if net_investment_leases > 0:
             logger.info(f"🧩 VICI Assets Final: {net_investment_leases:,.0f}")
        
        total_re_assets = re_properties + net_investment_leases

        # --- DIAGNOSTIC LOGGING (診斷日誌) ---
        if total_re_assets > 0 or total_debt_final > 0:
            logger.info(f"🏗️ REIT Extraction Diagnosis for {period_date}:")
            
            # 1. Assets Diagnosis
            if net_investment_leases > 0:
                logger.info(f"   [Assets] Vici Mode: SalesBucket({sales_type_total:,.0f}) + FinanceBucket({financing_total:,.0f}) -> Final({net_investment_leases:,.0f})")
            elif re_properties > 0:
                logger.info(f"   [Assets] Standard Mode: RealEstateProperties({re_properties:,.0f})")
            else:
                logger.warning(f"   [Assets] ⚠️ FAILED: No Real Estate Assets found!")

            # 2. Debt Diagnosis
            debt_source = "Standard" if total_debt_final == (standard_debt or 0) else "Sum-of-Parts"
            if total_debt_final != sum_of_parts and total_debt_final != (standard_debt or 0): # Fallback triggered
                 debt_source = "Implied/Adjusted"
            
            logger.info(f"   [Debt] Source: {debt_source} | Final: {total_debt_final:,.0f}")
            logger.info(f"   [Debt Breakdown] Unsecured({(unsecured_val or 0):,.0f}) + Mortgages({(mortgages_val or 0):,.0f}) + BankLoans({(term_loan_val or 0):,.0f})")
            
            # 3. LTV Check
            if total_debt_final > 0 and total_re_assets > 0:
                ltv = total_debt_final / total_re_assets
                logger.info(f"   [LTV Check] Debt/Asset Ratio: {ltv:.2%}")
        # -------------------------------------

        return REITBalanceSheet(
            period_date=period_date,
            total_assets=get_val("us-gaap:Assets"),
            total_liabilities=get_val("us-gaap:Liabilities"),
            total_equity=get_val(["us-gaap:StockholdersEquity", "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]),
            cash_and_equivalents=get_val(["us-gaap:CashAndCashEquivalentsAtCarryingValue", "us-gaap:Cash"]),
            marketable_securities=get_val("us-gaap:MarketableSecuritiesCurrent"),
            # REIT Specific
            real_estate_assets=total_re_assets if total_re_assets > 0 else None,
            
            # Map calculated values to the model
            unsecured_debt=unsecured_val if unsecured_val > 0 else None,
            mortgages=mortgages_val if mortgages_val > 0 else None,
            notes_payable=term_loan_val if term_loan_val > 0 else None, # Mapping Term Loans to Notes for simplicity
        )
    except Exception as e:
        logger.error(f"Error extracting REIT BS: {e}")
        return None


def _extract_corporate_cash_flow(df: pd.DataFrame) -> Optional[CorporateCashFlow]:
    """Extract Corporate Cash Flow"""
    try:
        get_val = lambda t, d=None: _get_fact_value_from_df(df, t, 'duration', d)
        # Dates calculation is omitted for brevity, assuming standard year if extracted elsewhere
        # Ideally extract dates from context, but keeping start/end generic for now
        period_end = date.today() 
        period_start = date.today()
        
        return CorporateCashFlow(
            period_start=period_start,
            period_end=period_end,
            ocf=get_val("us-gaap:NetCashProvidedByUsedInOperatingActivities"),
            dividends_paid=get_val("us-gaap:PaymentsOfDividends"),
            capex=get_val("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment")
        )
    except Exception as e:
        logger.error(f"Error extracting Corporate CF: {e}")
        return None


def _extract_reit_cash_flow(df: pd.DataFrame) -> Optional[REITCashFlow]:
    """Extract REIT Cash Flow with robust fallback for Capex"""
    try:
        get_val = lambda t, d=None: _get_fact_value_from_df(df, t, 'duration', d)
        period_end = date.today() 
        period_start = date.today()

        # 1. 優先嘗試：具體的房地產收購標籤 (通常在 XBRL 中為正數，代表支付的金額)
        re_investment = get_val([
            "us-gaap:PaymentsToAcquireRealEstate", 
            "us-gaap:PaymentsToAcquireRealEstateHeldForInvestment",
            "us-gaap:PaymentsToAcquireProperties",
            "us-gaap:PaymentsToAcquireProductiveAssets",
            "o:AcquisitionOfRealEstate"
        ])
        
        # 2. 備援機制：如果抓不到具體項目，使用「投資活動淨現金流」
        # 注意：投資活動現金流通常是負數 (流出)。
        # 我們的模型定義 Capex 為正數 (消耗)，所以這裡要乘以 -1。
        if re_investment is None:
            net_investing = get_val("us-gaap:NetCashProvidedByUsedInInvestingActivities")
            if net_investing is not None:
                # 如果是流出 (負數)，轉為正數；如果是流入 (正數，例如賣房多於買房)，則設為 0 (保守估計 Capex)
                re_investment = -net_investing if net_investing < 0 else 0.0

        return REITCashFlow(
            period_start=period_start,
            period_end=period_end,
            ocf=get_val("us-gaap:NetCashProvidedByUsedInOperatingActivities"),
            dividends_paid=get_val([
                "us-gaap:PaymentsOfDividendsCommonStock",
                "us-gaap:PaymentsOfDividends",
                "us-gaap:DividendsPaid",
                "us-gaap:Dividends"
            ]),
            real_estate_investment=re_investment
        )
    except Exception as e:
        logger.error(f"Error extracting REIT CF: {e}")
        return None


def _extract_corporate_income_statement(df: pd.DataFrame) -> Optional[CorporateIncomeStatement]:
    """Extract corporate/tech/manufacturing income statement"""
    try:
        period_start = date.today().replace(month=1, day=1)
        period_end = date.today()
        
        get_val = lambda t, d=None: _get_fact_value_from_df(df, t, 'duration', d)

        is_ = CorporateIncomeStatement(
            industry=IndustryType.CORPORATE,
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
        logger.error(f"Error extracting corporate income statement: {e}")
        return None


def _extract_bank_income_statement(df: pd.DataFrame, bs: BalanceSheetVariant) -> Optional[BankIncomeStatement]:
    """Extract banking institution income statement"""
    try:
        period_start = date.today().replace(month=1, day=1)
        period_end = date.today()
        
        get_val = lambda t, d=None: _get_fact_value_from_df(df, t, 'duration', d)
        
        # Calculate average earning assets (approximation using total assets)
        avg_earning_assets = bs.total_assets if bs.total_assets else None

        # NII Fallback Logic
        nii = get_val("us-gaap:NetInterestIncome")
        if nii is None:
            interest_income = get_val([
                "us-gaap:InterestAndDividendIncomeOperating",
                "us-gaap:InterestIncome",
                "us-gaap:InterestAndDividendIncome"
            ]) or 0.0
            interest_expense = get_val([
                "us-gaap:InterestExpense",
                "us-gaap:InterestExpenseOperating"
            ]) or 0.0
            
            if interest_income > 0:
                nii = interest_income - interest_expense

        is_ = BankIncomeStatement(
            industry=IndustryType.BANK,
            period_start=period_start,
            period_end=period_end,
            net_interest_income=nii,
            non_interest_income=get_val("us-gaap:NoninterestIncome"),
            provision_for_losses=get_val("us-gaap:ProvisionForLoanLeaseAndOtherLosses"),
            operating_expenses=get_val("us-gaap:OperatingExpenses"),
            net_income=get_val(["us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss"]),
            tax_expense=get_val("us-gaap:IncomeTaxExpenseBenefit"),
            avg_earning_assets=avg_earning_assets
        )
        return is_
    except Exception as e:
        logger.error(f"Error extracting bank income statement: {e}")
        return None


def _extract_reit_income_statement(df: pd.DataFrame) -> Optional[REITIncomeStatement]:
    """Extract REIT income statement"""
    try:
        period_start = date.today().replace(month=1, day=1)
        period_end = date.today()
        
        get_val = lambda t, d=None: _get_fact_value_from_df(df, t, 'duration', d)

        is_ = REITIncomeStatement(
            industry=IndustryType.REIT,
            period_start=period_start,
            period_end=period_end,
            rental_income=get_val([
                "us-gaap:OperatingLeaseRevenue",
                "us-gaap:RentalIncome",
                "us-gaap:Revenues",
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
            ]),
            property_operating_expenses=get_val("us-gaap:OperatingExpenses"),
            operating_expenses=get_val("us-gaap:OperatingExpenses"),
            net_income=get_val(["us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss"]),
            tax_expense=get_val("us-gaap:IncomeTaxExpenseBenefit"),
            depreciation=_get_fact_smart(
                df,
                standard_tags=[
                    "us-gaap:DepreciationDepletionAndAmortization", 
                    "us-gaap:DepreciationAndAmortization",
                    "us-gaap:Depreciation"
                ],
                fuzzy_keywords=["Depreciation", "RealEstate"],
                exclude_keywords=["Accumulated", "Reserve"]
            ),
            gains_on_sale=get_val("us-gaap:GainLossOnSaleOfProperties")
        )
        return is_
    except Exception as e:
        logger.error(f"Error extracting REIT income statement: {e}")
        return None


def _extract_income_statement_factory(df: pd.DataFrame, industry_type: IndustryType, bs: BalanceSheetVariant) -> Optional[IncomeStatementVariant]:
    """Factory function to extract the appropriate income statement based on industry type"""
    if industry_type == IndustryType.BANK:
        return _extract_bank_income_statement(df, bs)
    elif industry_type == IndustryType.REIT:
        return _extract_reit_income_statement(df)
    else:  # CORPORATE (default)
        return _extract_corporate_income_statement(df)
