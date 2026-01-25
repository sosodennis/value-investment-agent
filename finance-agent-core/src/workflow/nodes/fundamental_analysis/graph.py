"""
Fundamental Analysis Sub-graph implementation.
Handles the flow: Extract Intent -> Search/Verify -> Clarify (if needed).
Uses Command and interrupt for control flow.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from src.utils.logger import get_logger

from .financial_utils import fetch_financial_data
from .logic import select_valuation_model
from .structures import ValuationModel
from .subgraph_state import (
    FundamentalAnalysisInput,
    FundamentalAnalysisOutput,
    FundamentalAnalysisState,
)

logger = get_logger(__name__)

# --- Nodes ---


# Extraction nodes removed - now handled by intent_extraction subgraph


def financial_health_node(state: FundamentalAnalysisState) -> Command:
    """
    Fetch financial data from SEC EDGAR and generate Financial Health Report.
    """
    logger.info(
        f"DEBUG: [Fundamental Analysis] financial_health_node called with ticker={state.ticker}"
    )
    # Get resolved ticker from intent_extraction context
    resolved_ticker = state.intent_extraction.resolved_ticker or state.ticker
    if not resolved_ticker:
        logger.error(
            "--- Fundamental Analysis: No resolved ticker available, cannot proceed ---"
        )
        return Command(
            update={
                "current_node": "financial_health",
                "internal_progress": {"financial_health": "error"},
            },
            goto=END,
        )

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
            "fundamental": {
                "financial_reports": reports_data,
                "status": "model_selection",
            },
            "current_node": "financial_health",
            "internal_progress": {
                "financial_health": "done",
                "model_selection": "running",
            },
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


def model_selection_node(state: FundamentalAnalysisState) -> Command:
    """
    Select appropriate valuation model based on company profile and financial health.
    """
    logger.info("DEBUG: [Fundamental Analysis] model_selection_node called")
    from .structures import CompanyProfile

    # Get company profile from intent_extraction context
    profile = (
        CompanyProfile(**state.intent_extraction.company_profile)
        if state.intent_extraction.company_profile
        else None
    )
    resolved_ticker = state.intent_extraction.resolved_ticker or state.ticker

    if not profile:
        logger.warning(
            "--- Fundamental Analysis: Missing company profile, cannot select model ---"
        )
        return Command(
            update={
                "fundamental": {"status": "clarifying"},
                "current_node": "model_selection",
                "internal_progress": {"model_selection": "waiting"},
            },
            goto="clarifying",
        )

    # Select model based on profile
    model, reasoning = select_valuation_model(profile)

    # Enhance reasoning with financial health insights (using latest report)
    if state.fundamental.financial_reports:
        try:
            from .financial_models import FinancialReport

            # Use most recent year (index 0)
            latest_report_data = state.fundamental.financial_reports[0]
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
            "fundamental": {
                "analysis_output": {
                    "ticker": resolved_ticker,
                    "model_type": model.value,
                    "company_name": profile.name,
                    "sector": profile.sector,
                    "industry": profile.industry,
                    "reasoning": reasoning,
                    "financial_reports": state.fundamental.financial_reports,
                }
            },
            "current_node": "model_selection",
            "internal_progress": {
                "model_selection": "done",
            },
            # [BSP Fix] Emit status immediately to bypass LangGraph's sync barrier
            # allowing the UI to update without waiting for parallel branches (TA/News)
            "node_statuses": {"fundamental_analysis": "done"},
        },
        goto=END,
    )


# Clarification node removed - now handled by intent_extraction subgraph


# --- Graph Construction ---


def build_fundamental_subgraph():
    """纯函數：構建並編譯子圖"""
    builder = StateGraph(
        FundamentalAnalysisState,
        input=FundamentalAnalysisInput,
        output=FundamentalAnalysisOutput,
    )
    builder.add_node("financial_health", financial_health_node)
    builder.add_node("model_selection", model_selection_node)
    builder.add_edge(START, "financial_health")
    builder.add_edge("financial_health", "model_selection")

    # 注意：這裡不需要傳入 checkpointer，因為它會繼承父圖的
    return builder.compile()
