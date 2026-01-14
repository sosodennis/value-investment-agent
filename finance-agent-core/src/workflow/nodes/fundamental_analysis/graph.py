"""
Fundamental Analysis Sub-graph implementation.
Handles the flow: Extract Intent -> Search/Verify -> Clarify (if needed).
Uses Command and interrupt for control flow.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from src.utils.logger import get_logger

from ...state import AgentState
from .extraction import (
    deduplicate_candidates,
    extract_candidates_from_search,
    extract_intent,
)
from .financial_utils import fetch_financial_data
from .logic import select_valuation_model, should_request_clarification
from .structures import ValuationModel
from .tools import get_company_profile, search_ticker, web_search

logger = get_logger(__name__)

# --- Nodes ---


def extraction_node(state: AgentState) -> Command:
    """Extract company and model from user query."""
    user_query = state.user_query
    if not user_query:
        logger.warning(
            "--- Fundamental Analysis: No query provided, requesting clarification ---"
        )
        return Command(
            update={
                "status": "clarifying",
                "fundamental_analysis_output": {
                    "status": "clarification_needed",
                    "error": "No query provided",
                },
            },
            goto="clarifying",
        )

    logger.info(f"--- Fundamental Analysis: Extracting intent from: {user_query} ---")
    intent = extract_intent(user_query)
    return Command(
        update={
            "extracted_intent": intent.model_dump(),
            "node_statuses": {"fundamental_analysis": "running"},
        },
        goto="searching",
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
            clean_query = (
                state.user_query.replace("Valuate", "").replace("Value", "").strip()
            )
            search_queries.append(clean_query)
        else:
            logger.warning(
                "--- Fundamental Analysis: Search query missing, requesting clarification ---"
            )
            return Command(update={"status": "clarifying"}, goto="clarifying")

    logger.info(f"--- Fundamental Analysis: Searching for queries: {search_queries} ---")
    candidate_map = {}

    # === Execute Search on All Queries ===
    for query in search_queries:
        # 1. Try Yahoo Finance Search
        yf_candidates = search_ticker(query)

        # Check for high confidence matches (Short-circuit removed per user request to always do dual-search)
        high_confidence_candidates = [c for c in yf_candidates if c.confidence >= 0.9]
        if high_confidence_candidates:
            logger.info(
                f"--- Fundamental Analysis: High confidence match found via Yahoo for '{query}': {[c.symbol for c in high_confidence_candidates]} ---"
            )

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
    logger.info(f"Final candidates: {[c.symbol for c in final_candidates]}")

    return Command(
        update={
            "ticker_candidates": [c.model_dump() for c in final_candidates],
            "status": "deciding",
            "node_statuses": {"fundamental_analysis": "running"},
        },
        goto="deciding",
    )


def decision_node(state: AgentState) -> Command:
    """Decide if ticker is resolved or needs clarification."""
    candidates = state.ticker_candidates or []

    if not candidates:
        logger.warning(
            "--- Fundamental Analysis: No candidates found, requesting clarification ---"
        )
        return Command(update={"status": "clarifying"}, goto="clarifying")

    # Check for ambiguity
    from .structures import TickerCandidate

    candidate_objs = [TickerCandidate(**c) for c in candidates]

    if should_request_clarification(candidate_objs):
        logger.warning(
            "--- Fundamental Analysis: Ambiguity detected, requesting clarification ---"
        )
        return Command(update={"status": "clarifying"}, goto="clarifying")

    # Resolved - proceed to financial health check
    resolved_ticker = candidate_objs[0].symbol
    logger.info(f"--- Fundamental Analysis: Ticker resolved to {resolved_ticker} ---")
    profile = get_company_profile(resolved_ticker)

    if not profile:
        logger.warning(
            f"--- Fundamental Analysis: Could not fetch profile for {resolved_ticker}, requesting clarification ---"
        )
        return Command(update={"status": "clarifying"}, goto="clarifying")

    return Command(
        update={
            "resolved_ticker": resolved_ticker,
            "company_profile": profile.model_dump(),
            "status": "financial_health",
        },
        goto="financial_health",
    )


def financial_health_node(state: AgentState) -> Command:
    """
    Fetch financial data from SEC EDGAR and generate Financial Health Report.
    """
    resolved_ticker = state.resolved_ticker
    logger.info(
        f"--- Fundamental Analysis: Fetching financial health data for {resolved_ticker} ---"
    )

    # Fetch financial data (mult-year)
    financial_reports = fetch_financial_data(resolved_ticker, years=3)

    reports_data = []

    if financial_reports:
        import textwrap

        from .financial_models import (
            ComputedProvenance,
            FinancialServicesExtension,
            IndustrialExtension,
            ManualProvenance,
            RealEstateExtension,
            XBRLProvenance,
        )

        # Helper logging functions - handle TraceableField objects with new Provenance
        def wrap_text(text: str, width: int = 40) -> str:
            """Wrap text to a specified width."""
            return "\n".join(textwrap.wrap(text, width=width))

        def src(v):
            """Extract source metadata from TraceableField"""
            if v is None or not hasattr(v, "provenance"):
                return ""
            p = v.provenance
            if isinstance(p, XBRLProvenance):
                return f" | [XBRL: {p.concept}]"
            elif isinstance(p, ComputedProvenance):
                return f" | [Calc: {p.expression}]"
            elif isinstance(p, ManualProvenance):
                return f" | [Manual: {p.description}]"
            return ""

        def fmt_currency(v):
            """Format currency values"""
            if v is None:
                return "None"
            val = v.value if hasattr(v, "value") else v
            if val is None:
                return "None"
            try:
                fval = float(val)
                res = f"${fval:,.0f}{src(v)}"
            except (ValueError, TypeError):
                res = f"{val}{src(v)}"
            return wrap_text(res)

        def fmt_num(v):
            """Format numeric values (non-currency)"""
            if v is None:
                return "None"
            val = v.value if hasattr(v, "value") else v
            if val is None:
                return "None"
            try:
                fval = float(val)
                res = f"{fval:,.0f}{src(v)}"
            except (ValueError, TypeError):
                res = f"{val}{src(v)}"
            return wrap_text(res)

        def fmt_str(v):
            """Format string values"""
            if v is None:
                return "None"
            val = v.value if hasattr(v, "value") else v
            if val is None:
                return "None"
            res = f"{val}{src(v)}"
            return wrap_text(res)

        def pct(v):
            """Format percentage values"""
            if v is None:
                return "None"
            val = v.value if hasattr(v, "value") else v
            if val is None:
                return "None"
            try:
                fval = float(val)
                res = f"{fval:.2%}{src(v)}"
            except (ValueError, TypeError):
                res = f"{val}{src(v)}"
            return wrap_text(res)

        def ratio(num, den):
            """Safe ratio calculation"""
            n_val = num.value if hasattr(num, "value") else num
            d_val = den.value if hasattr(den, "value") else den

            if n_val is None or d_val is None:
                return "None"
            try:
                n = float(n_val)
                d = float(d_val)
                if d == 0:
                    return "None (Div0)"
                res = f"{n / d:.2f}"
                return wrap_text(res)
            except (ValueError, TypeError):
                return "None"

        logger.info(
            f"✅ Generated {len(financial_reports)} Financial Health Reports for {resolved_ticker}"
        )

        # Build Table Data
        # Sort reports by year descending (usually they come sorted but ensure it)
        # Assuming fetch returns somewhat ordered, but let's key off fiscal_year if possible
        # Or just use list order.

        # Headers
        years_headers = []
        for r in financial_reports:
            fy = r.base.fiscal_year.value if r.base.fiscal_year else "N/A"
            fp = r.base.fiscal_period.value if r.base.fiscal_period else "N/A"
            years_headers.append(f"{fy} ({fp})")

        headers = ["Metric"] + years_headers

        # --- Base Model Table ---
        base_rows = []

        # Computed Ratios first or last? Let's put them first as summary.
        roe_row = ["ROE"]
        de_row = ["Debt/Equity"]

        for r in financial_reports:
            roe_row.append(ratio(r.base.net_income, r.base.total_equity))
            de_row.append(ratio(r.base.total_liabilities, r.base.total_equity))

        base_rows.append(roe_row)
        base_rows.append(de_row)
        base_rows.append(["---"] * len(headers))  # Separator

        # Metric mapping: (Label, AttributeName, Formatter)
        base_metrics = [
            ("CIK", "cik", fmt_str),
            ("SIC Code", "sic_code", fmt_str),
            ("Company Name", "company_name", fmt_str),
            ("Shares Outstanding", "shares_outstanding", fmt_num),
            ("Revenue", "total_revenue", fmt_currency),
            ("Net Income", "net_income", fmt_currency),
            ("Income Tax Expense", "income_tax_expense", fmt_currency),
            ("Cash & Eq", "cash_and_equivalents", fmt_currency),
            ("Total Assets", "total_assets", fmt_currency),
            ("Total Liabilities", "total_liabilities", fmt_currency),
            ("Total Equity", "total_equity", fmt_currency),
            ("OCF", "operating_cash_flow", fmt_currency),
        ]

        for label, attr, formatter in base_metrics:
            row = [label]
            for r in financial_reports:
                val = getattr(r.base, attr, None)
                row.append(formatter(val))
            base_rows.append(row)

        # print(f"\n📊 [{resolved_ticker}] Base Financials & Ratios")
        # print(tabulate(base_rows, headers=headers, tablefmt="grid"))

        # --- Extension Model Table ---
        # Determine extension type from first report (assume consistent)
        first_ext = financial_reports[0].extension if financial_reports else None

        if first_ext:
            ext_rows = []
            ext_metrics = []
            # title = "Extension Metrics"

            if isinstance(first_ext, IndustrialExtension):
                # title = "🏭 Industrial Metrics"
                ext_metrics = [
                    ("Inventory", "inventory"),
                    ("Accounts Receivable", "accounts_receivable"),
                    ("COGS", "cogs"),
                    ("R&D", "rd_expense"),
                    ("SG&A", "sga_expense"),
                    ("Capex", "capex"),
                ]
            elif isinstance(first_ext, FinancialServicesExtension):
                # title = "🏦 Banking Metrics"
                ext_metrics = [
                    ("Loans", "loans_and_leases"),
                    ("Deposits", "deposits"),
                    ("Allowance for Credit Losses", "allowance_for_credit_losses"),
                    ("Interest Income", "interest_income"),
                    ("Interest Expense", "interest_expense"),
                    ("Provision for Loan Losses", "provision_for_loan_losses"),
                ]
            elif isinstance(first_ext, RealEstateExtension):
                # title = "🏠 Real Estate Metrics"
                ext_metrics = [
                    ("Real Estate Assets", "real_estate_assets"),
                    ("Accumulated Dep", "accumulated_depreciation"),
                    ("Dep & Amort", "depreciation_and_amortization"),
                    ("FFO", "ffo"),
                ]

            for label, attr in ext_metrics:
                row = [label]
                for r in financial_reports:
                    # Need to check if extension exists for this specific report (robustness)
                    ext = r.extension
                    if ext:
                        val = getattr(ext, attr, None)
                        row.append(fmt_currency(val))
                    else:
                        row.append("None")
                ext_rows.append(row)

            # print(f"\n{title}")
            # print(tabulate(ext_rows, headers=headers, tablefmt="grid"))

        reports_data = [r.model_dump() for r in financial_reports]
    else:
        logger.warning(
            f"⚠️  Could not fetch financial data for {resolved_ticker}, proceeding without it"
        )
        reports_data = []

    from langchain_core.messages import AIMessage

    return Command(
        update={
            "financial_reports": reports_data,
            "status": "model_selection",
            "messages": [
                AIMessage(
                    content="",
                    additional_kwargs={
                        "type": "financial_report",
                        "data": reports_data,
                        "agent_id": "fundamental_analysis",
                    },
                )
            ]
            if reports_data
            else [],
        },
        goto="model_selection",
    )


def model_selection_node(state: AgentState) -> Command:
    """
    Select appropriate valuation model based on company profile and financial health.
    """
    from .structures import CompanyProfile

    profile = CompanyProfile(**state.company_profile) if state.company_profile else None
    resolved_ticker = state.resolved_ticker

    if not profile:
        logger.warning(
            "--- Fundamental Analysis: Missing company profile, cannot select model ---"
        )
        return Command(update={"status": "clarifying"}, goto="clarifying")

    # Select model based on profile
    model, reasoning = select_valuation_model(profile)

    # Enhance reasoning with financial health insights (using latest report)
    if state.financial_reports:
        try:
            from .financial_models import FinancialReport

            # Use most recent year (index 0)
            latest_report_data = state.financial_reports[0]
            # FinancialReport is a Pydantic model, so we can parse it
            report = FinancialReport(**latest_report_data)
            base = report.base

            # Add financial health context to reasoning
            fy = base.fiscal_year.value if base.fiscal_year else "Unknown"
            health_context = f"\n\nFinancial Health Insights (FY{fy}):\n"

            # Helper to extract value from TraceableField
            def get_val(field):
                if field is None:
                    return None
                return field.value if hasattr(field, "value") else field

            # Extract basic metrics
            net_income_val = get_val(base.net_income)
            equity_val = get_val(base.total_equity)
            ocf_val = get_val(base.operating_cash_flow)

            # Derived ratios for reasoning context
            roe_val = (
                (net_income_val / equity_val)
                if (net_income_val and equity_val)
                else None
            )

            health_context += (
                f"- Net Income: ${net_income_val:,.0f}"
                if net_income_val is not None
                else ""
            )
            health_context += (
                f"\n- Total Equity: ${equity_val:,.0f}"
                if equity_val is not None
                else ""
            )
            health_context += f"\n- ROE: {roe_val:.2%}" if roe_val is not None else ""
            health_context += f"\n- OCF: ${ocf_val:,.0f}" if ocf_val is not None else ""

            reasoning += health_context
        except Exception as e:
            logger.warning(f"⚠️  Could not parse financial report for insights: {e}")

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
            "fundamental_analysis_output": {
                "ticker": resolved_ticker,
                "model_type": model.value,
                "company_name": profile.name,
                "sector": profile.sector,
                "industry": profile.industry,
                "reasoning": reasoning,
                "financial_reports": state.financial_reports,
            },
            "node_statuses": {
                "fundamental_analysis": "done",
                "financial_news_research": "running",
            },
        },
        goto=END,
    )


def clarification_node(state: AgentState) -> Command:
    """
    Triggers an interrupt to ask the user to select a ticker or provide clarification.
    """
    logger.warning(
        "--- Fundamental Analysis: Ticker Ambiguity Detected. Waiting for user input... ---"
    )

    from ...interrupts import HumanTickerSelection
    from .extraction import IntentExtraction

    # Trigger interrupt with candidates
    interrupt_payload = HumanTickerSelection(
        candidates=state.ticker_candidates or [],
        intent=IntentExtraction(**state.extracted_intent)
        if state.extracted_intent
        else None,
        reason="Multiple tickers found or ambiguity detected.",
    )
    user_input = interrupt(interrupt_payload.model_dump())
    logger.info(f"--- Fundamental Analysis: Received user input: {user_input} ---")

    # user_input is what the frontend sends back, e.g. { "selected_symbol": "GOOGL" }
    selected_symbol = user_input.get("selected_symbol") or user_input.get("ticker")

    if not selected_symbol:
        # Fallback to top candidate if resumed without choice
        candidates = state.ticker_candidates or []
        if candidates:
            top = candidates[0]
            selected_symbol = top.get("symbol") if isinstance(top, dict) else top.symbol

    if selected_symbol:
        logger.info(f"✅ User selected or fallback symbol: {selected_symbol}. Resolving...")
        profile = get_company_profile(selected_symbol)
        if profile:
            from langchain_core.messages import AIMessage, HumanMessage

            # Persist interactive messages to history
            new_messages = [
                AIMessage(
                    content="",
                    additional_kwargs={
                        "type": "ticker_selection",
                        "data": interrupt_payload.model_dump(),
                        "agent_id": "fundamental_analysis",
                    },
                ),
                HumanMessage(content=f"Selected Ticker: {selected_symbol}"),
            ]

            return Command(
                update={
                    "resolved_ticker": selected_symbol,
                    "company_profile": profile.model_dump(),
                    "status": "financial_health",
                    "messages": new_messages,
                },
                goto="financial_health",
            )

    # If even fallback fails, retry extraction
    logger.warning("--- Fundamental Analysis: Resolution failed, retrying extraction ---")
    return Command(update={"status": "extraction"}, goto="extraction")


# Helper for initialization
fundamental_analysis_subgraph = None


async def get_fundamental_analysis_subgraph():
    """Lazy-initialize and return the fundamental_analysis subgraph."""
    global fundamental_analysis_subgraph
    if fundamental_analysis_subgraph is None:
        # 1. Build Subgraph
        builder = StateGraph(AgentState)
        builder.add_node("extraction", extraction_node)
        builder.add_node("searching", searching_node)
        builder.add_node("deciding", decision_node)
        builder.add_node("financial_health", financial_health_node)
        builder.add_node("model_selection", model_selection_node)
        builder.add_node("clarifying", clarification_node)
        builder.add_edge(START, "extraction")

        # 2. Compile
        # Note: No checkpointer passed here; it will be inherited from the parent graph
        fundamental_analysis_subgraph = builder.compile()

    return fundamental_analysis_subgraph
