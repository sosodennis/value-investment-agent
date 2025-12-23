"""
Planner Sub-graph implementation.
Handles the flow: Extract Intent -> Search/Verify -> Clarify (if needed).
Uses Command and interrupt for control flow.
"""

from typing import Annotated, Dict, Any, List, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage

from .extraction import extract_intent, extract_candidates_from_search, deduplicate_candidates
from .tools import search_ticker, web_search, get_company_profile
from .logic import select_valuation_model, should_request_clarification
from .structures import PlannerOutput, ValuationModel
from .financial_utils import fetch_financial_data
from ...state import AgentState


# --- Nodes ---

def extraction_node(state: AgentState) -> Command:
    """Extract company and model from user query."""
    user_query = state.user_query
    if not user_query:
        print("--- Planner: No query provided, requesting clarification ---")
        return Command(
            update={
                "status": "clarifying",
                "planner_output": {"status": "clarification_needed", "error": "No query provided"}
            },
            goto="clarifying"
        )
    
    print(f"--- Planner: Extracting intent from: {user_query} ---")
    intent = extract_intent(user_query)
    return Command(
        update={
            "extracted_intent": intent.model_dump(),
            "status": "searching"
        },
        goto="searching"
    )

def searching_node(state: AgentState) -> Command:
    """Search for the ticker based on extracted intent."""
    intent = state.extracted_intent or {}
    
    # Extract explicit fields
    extracted_ticker = intent.get("ticker")
    extracted_name = intent.get("company_name")
    
    # === Multi-Query Strategy ===
    search_queries = []
    
    # 1. Company Name (Broad Match) - Priorities catching multiple share classes (GOOG vs GOOGL)
    if extracted_name:
        search_queries.append(extracted_name)
        
    # 2. Ticker (Exact Match) - Add if distinct from name
    if extracted_ticker and extracted_ticker != extracted_name:
        search_queries.append(extracted_ticker)
    
    # If explicit extraction failed, fallback to the raw query (heuristic)
    if not search_queries:
        if state.user_query:
             # Basic heuristic cleanup
             clean_query = state.user_query.replace("Valuate", "").replace("Value", "").strip()
             search_queries.append(clean_query)
        else:
            print("--- Planner: Search query missing, requesting clarification ---")
            return Command(
                update={"status": "clarifying"},
                goto="clarifying"
            )

    print(f"--- Planner: Searching for queries: {search_queries} ---")
    candidate_map = {}

    # === Execute Search on All Queries ===
    for query in search_queries:
        # 1. Try Yahoo Finance Search
        yf_candidates = search_ticker(query)
        
        # Check for high confidence matches (Short-circuit removed per user request to always do dual-search)
        high_confidence_candidates = [c for c in yf_candidates if c.confidence >= 0.9]
        if high_confidence_candidates:
             print(f"--- Planner: High confidence match found via Yahoo for '{query}': {[c.symbol for c in high_confidence_candidates]} ---")
    
        for c in yf_candidates:
            # Deduplicate by symbol
            if c.symbol not in candidate_map:
                candidate_map[c.symbol] = c
            else:
                # Merge: Keep the one with higher confidence
                if c.confidence > candidate_map[c.symbol].confidence:
                    candidate_map[c.symbol] = c

    # 2. Web Search fallback (Always run to ensure coverage)
    # Use the primary query (Name or Ticker) for web search
    primary_query = search_queries[0]
    # Use quotes to force exact match and reduce noise
    search_results = web_search(f'"{primary_query}" stock ticker symbol official')
    
    web_candidates = extract_candidates_from_search(primary_query, search_results)
    
    for c in web_candidates:
        if c.symbol in candidate_map:
             if c.confidence > candidate_map[c.symbol].confidence:
                 candidate_map[c.symbol] = c
        else:
            candidate_map[c.symbol] = c

    final_candidates = deduplicate_candidates(list(candidate_map.values()))
    print(f"Final candidates: {[c.symbol for c in final_candidates]}")

    return Command(
        update={
            "ticker_candidates": [c.model_dump() for c in final_candidates],
            "status": "deciding"
        },
        goto="deciding"
    )

def decision_node(state: AgentState) -> Command:
    """Decide if ticker is resolved or needs clarification."""
    candidates = state.ticker_candidates or []
    
    if not candidates:
        print("--- Planner: No candidates found, requesting clarification ---")
        return Command(
            update={"status": "clarifying"},
            goto="clarifying"
        )

    # Check for ambiguity
    from .structures import TickerCandidate
    candidate_objs = [TickerCandidate(**c) for c in candidates]
    
    if should_request_clarification(candidate_objs):
        print("--- Planner: Ambiguity detected, requesting clarification ---")
        return Command(
            update={"status": "clarifying"},
            goto="clarifying"
        )
    
    # Resolved - proceed to financial health check
    resolved_ticker = candidate_objs[0].symbol
    print(f"--- Planner: Ticker resolved to {resolved_ticker} ---")
    profile = get_company_profile(resolved_ticker)
    
    if not profile:
        print(f"--- Planner: Could not fetch profile for {resolved_ticker}, requesting clarification ---")
        return Command(
            update={"status": "clarifying"},
            goto="clarifying"
        )

    return Command(
        update={
            "resolved_ticker": resolved_ticker,
            "company_profile": profile.model_dump(),
            "status": "financial_health"
        },
        goto="financial_health"
    )

def financial_health_node(state: AgentState) -> Command:
    """
    Fetch financial data from SEC EDGAR and generate Financial Health Report.
    """
    resolved_ticker = state.resolved_ticker
    print(f"--- Planner: Fetching financial health data for {resolved_ticker} ---")
    
    # Fetch financial data (mult-year)
    financial_reports = fetch_financial_data(resolved_ticker, years=3)
    
    reports_data = []
    
    if financial_reports:
        # Helper logging functions - handle TraceableField objects
        def src(v):
            """Extract source metadata from TraceableField"""
            if v is None or not hasattr(v, 'source_tags'):
                return ""
            if getattr(v, 'is_calculated', False):
                logic = getattr(v, 'formula_logic', 'N/A')
                return f" | [Calc: {logic}]"
            tags = getattr(v, 'source_tags', [])
            if tags:
                return f" | [Tags: {', '.join(tags)}]"
            return ""

        def fmt(v):
            """Format currency values, handling TraceableField"""
            if v is None:
                return "N/A"
            val = v.value if hasattr(v, 'value') else v
            if val is None: return "N/A"
            return f"${val:,.0f}{src(v)}"
        
        def pct(v):
            """Format percentage values, handling TraceableField"""
            if v is None:
                return "N/A"
            val = v.value if hasattr(v, 'value') else v
            if val is None: return "N/A"
            return f"{val:.2%}{src(v)}"
        
        def ratio(v):
            """Format ratio values, handling TraceableField"""
            if v is None:
                return "N/A"
            val = v.value if hasattr(v, 'value') else v
            if val is None: return "N/A"
            return f"{val:.2f}{src(v)}"

        print(f"✅ Generated {len(financial_reports)} Financial Health Reports for {resolved_ticker}")
        
        for i, report in enumerate(financial_reports):
            print(f"\n📅 --- Fiscal Year: {report.fiscal_period} ({report.is_.industry.value}) ---")
            print(f"   • Current Ratio: {ratio(report.current_ratio)}")
            print(f"   • Debt/Equity: {ratio(report.debt_to_equity)}")
            print(f"   • ROE: {pct(report.return_on_equity)}")
            print(f"   • FCF: {fmt(report.free_cash_flow)}")
            
            # Industry-specific logging
            from .financial_models import (
                CorporateIncomeStatement, BankIncomeStatement, REITIncomeStatement,
                CorporateBalanceSheet, BankBalanceSheet, REITBalanceSheet,
                CorporateCashFlow, REITCashFlow
            )
            
            print(f"   📉 Income Statement ({report.fiscal_period}):")
            if isinstance(report.is_, CorporateIncomeStatement):
                print(f"     - Revenue: {fmt(report.is_.revenue)}")
                print(f"     - Gross Profit: {fmt(report.is_.gross_profit)}")
                print(f"     - Operating Income: {fmt(report.is_.operating_income)}")
                print(f"     - Net Income: {fmt(report.is_.net_income)}")
            elif isinstance(report.is_, BankIncomeStatement):
                print(f"     - Net Interest Income: {fmt(report.is_.net_interest_income)}")
                print(f"     - Non-Interest Income: {fmt(report.is_.non_interest_income)}")
                print(f"     - Total Revenue: {fmt(report.is_.total_revenue)}")
                print(f"     - Net Interest Margin: {pct(report.is_.net_interest_margin)}")
                print(f"     - Efficiency Ratio: {pct(report.is_.efficiency_ratio)}")
                print(f"     - Net Income: {fmt(report.is_.net_income)}")
            elif isinstance(report.is_, REITIncomeStatement):
                print(f"     - Rental Income: {fmt(report.is_.rental_income)}")
                print(f"     - FFO (Funds From Operations): {fmt(report.is_.funds_from_operations)}")
                print(f"     - Net Income: {fmt(report.is_.net_income)}")
            
            # Detailed Statement Logging
            print(f"   📊 Balance Sheet ({report.fiscal_period}):")
            print(f"     - Cash & Eq: {fmt(report.bs.cash_and_equivalents)}")
            if report.bs.total_liquidity and (report.bs.marketable_securities or report.bs.marketable_securities_noncurrent):
                 print(f"     - Marketable Securities (Current): {fmt(report.bs.marketable_securities)}")
                 print(f"     - Marketable Securities (Non-Current): {fmt(report.bs.marketable_securities_noncurrent)}")
                 print(f"     - Total Liquidity: {fmt(report.bs.total_liquidity)}")
            print(f"     - Total Assets: {fmt(report.bs.total_assets)}")
            print(f"     - Total Debt: {fmt(report.bs.total_debt)}")
            print(f"     - Total Equity: {fmt(report.bs.total_equity)}")
            
            if isinstance(report.bs, CorporateBalanceSheet):
                print(f"     - Current Assets: {fmt(report.bs.assets_current)}")
                print(f"     - Current Liabilities: {fmt(report.bs.liabilities_current)}")
                print(f"     - Inventory: {fmt(report.bs.inventory)}")
                print(f"     - Receivables: {fmt(report.bs.receivables_net)}")
                print(f"     - Lease Liabilities: {fmt(report.bs.total_lease_liabilities)}")
                print(f"     - Adjusted Debt: {fmt(report.bs.adjusted_total_debt)}")
                print(f"     - Net Debt: {fmt(report.bs.net_debt)}")
            elif isinstance(report.bs, BankBalanceSheet):
                print(f"     - Total Deposits: {fmt(report.bs.total_deposits)}")
                print(f"     - Net Loans: {fmt(report.bs.net_loans)}")
            elif isinstance(report.bs, REITBalanceSheet):
                print(f"     - Real Estate Assets: {fmt(report.bs.real_estate_assets)}")
                print(f"     - Unsecured Debt: {fmt(report.bs.unsecured_debt)}")
                print(f"     - Mortgages: {fmt(report.bs.mortgages)}")

            print(f"   💸 Cash Flow ({report.fiscal_period}):")
            print(f"     - OCF: {fmt(report.cf.ocf)}")
            print(f"     - Dividends Paid: {fmt(report.cf.dividends_paid)}")
            if isinstance(report.cf, CorporateCashFlow):
                print(f"     - Capex: {fmt(report.cf.capex)}")
            elif isinstance(report.cf, REITCashFlow):
                print(f"     - RE Investment: {fmt(report.cf.real_estate_investment)}")

            
            reports_data.append(report.model_dump())

    else:
        print(f"⚠️  Could not fetch financial data for {resolved_ticker}, proceeding without it")
        reports_data = []
    
    return Command(
        update={
            "financial_reports": reports_data,
            "status": "model_selection"
        },
        goto="model_selection"
    )


def model_selection_node(state: AgentState) -> Command:
    """
    Select appropriate valuation model based on company profile and financial health.
    """
    from .structures import CompanyProfile
    
    profile = CompanyProfile(**state.company_profile) if state.company_profile else None
    resolved_ticker = state.resolved_ticker
    
    if not profile:
        print("--- Planner: Missing company profile, cannot select model ---")
        return Command(
            update={"status": "clarifying"},
            goto="clarifying"
        )
    
    # Select model based on profile
    model, reasoning = select_valuation_model(profile)
    
    # Enhance reasoning with financial health insights (using latest report)
    if state.financial_reports:
        try:
            from .financial_models import FinancialHealthReport
            # Use most recent year (index 0)
            latest_report_data = state.financial_reports[0]
            report = FinancialHealthReport(**latest_report_data)
            
            # Add financial health context to reasoning
            health_context = f"\n\nFinancial Health Insights ({report.fiscal_period}):\n"
            
            # Helper to extract value from TraceableField
            def get_val(field):
                return field.value if hasattr(field, 'value') else field
            
            current_ratio_val = get_val(report.current_ratio)
            debt_to_equity_val = get_val(report.debt_to_equity)
            roe_val = get_val(report.return_on_equity)
            fcf_val = get_val(report.free_cash_flow)
            
            health_context += f"- Current Ratio: {current_ratio_val:.2f}" if current_ratio_val is not None else ""
            health_context += f"\n- Debt-to-Equity: {debt_to_equity_val:.2f}" if debt_to_equity_val is not None else ""
            health_context += f"\n- ROE: {roe_val:.2%}" if roe_val is not None else ""
            health_context += f"\n- Free Cash Flow: ${fcf_val:,.0f}" if fcf_val is not None else ""
            
            reasoning += health_context
        except Exception as e:
            print(f"⚠️  Could not parse financial report for insights: {e}")
    
    # Map model_type for calculation node compatibility
    model_type_map = {
        ValuationModel.DCF_GROWTH: "saas",
        ValuationModel.DCF_STANDARD: "saas",
        ValuationModel.DDM: "bank",
        ValuationModel.FFO: "saas",
        ValuationModel.EV_REVENUE: "saas",
        ValuationModel.EV_EBITDA: "saas",
    }
    model_type = model_type_map.get(model, "saas")

    return Command(
        update={
            "ticker": resolved_ticker,
            "model_type": model_type,
            "planner_output": {
                "ticker": resolved_ticker,
                "model_type": model.value,
                "company_name": profile.name,
                "sector": profile.sector,
                "industry": profile.industry,
                "reasoning": reasoning,
                "financial_reports": state.financial_reports
            },
            "status": "done"
        },
        goto=END
    )


def clarification_node(state: AgentState) -> Command:
    """
    Triggers an interrupt to ask the user to select a ticker or provide clarification.
    """
    print("--- Planner: Ticker Ambiguity Detected. Waiting for user input... ---")
    
    from ...interrupts import HumanTickerSelection
    from .extraction import IntentExtraction
    
    # Trigger interrupt with candidates
    interrupt_payload = HumanTickerSelection(
        candidates=state.ticker_candidates or [],
        intent=IntentExtraction(**state.extracted_intent) if state.extracted_intent else None,
        reason="Multiple tickers found or ambiguity detected."
    )
    user_input = interrupt(interrupt_payload.model_dump())

    # user_input is what the frontend sends back, e.g. { "selected_symbol": "GOOGL" }
    selected_symbol = user_input.get("selected_symbol") or user_input.get("ticker")
    
    if not selected_symbol:
        # Fallback to top candidate if resumed without choice
        candidates = state.ticker_candidates or []
        if candidates:
            top = candidates[0]
            selected_symbol = top.get("symbol") if isinstance(top, dict) else top.symbol

    if selected_symbol:
        print(f"✅ User selected or fallback symbol: {selected_symbol}. Resolving...")
        profile = get_company_profile(selected_symbol)
        if profile:
            return Command(
                update={
                    "resolved_ticker": selected_symbol,
                    "company_profile": profile.model_dump(),
                    "status": "financial_health"
                },
                goto="financial_health"
            )

    # If even fallback fails, retry extraction
    print("--- Planner: Resolution failed, retrying extraction ---")
    return Command(
        update={"status": "extraction"},
        goto="extraction"
    )


from langgraph.checkpoint.memory import MemorySaver

# --- Build Sub-graph ---
def create_planner_subgraph():
    builder = StateGraph(AgentState)
    
    builder.add_node("extraction", extraction_node)
    builder.add_node("searching", searching_node)
    builder.add_node("deciding", decision_node)
    builder.add_node("financial_health", financial_health_node)
    builder.add_node("model_selection", model_selection_node)
    builder.add_node("clarifying", clarification_node)
    
    builder.add_edge(START, "extraction")
    # Transitions are handled by Command() in each node
    
    memory = MemorySaver()
    return builder.compile(checkpointer=memory)

planner_subgraph = create_planner_subgraph()
