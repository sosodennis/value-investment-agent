import textwrap
import time

from langgraph.graph import END
from langgraph.types import Command

from src.common.utils.logger import get_logger
from src.interface.schemas import AgentOutputArtifact, ArtifactReference
from src.services.artifact_manager import artifact_manager

from .financial_utils import fetch_financial_data
from .logic import select_valuation_model
from .mappers import summarize_fundamental_for_preview
from .structures import CompanyProfile, ValuationModel
from .subgraph_state import (
    FundamentalAnalysisState,
)

logger = get_logger(__name__)


def financial_health_node(state: FundamentalAnalysisState) -> Command:
    """
    Fetch financial data from SEC EDGAR and generate Financial Health Report.
    """
    # Get resolved ticker from intent_extraction context
    intent_ctx = state.get("intent_extraction", {})
    resolved_ticker = intent_ctx.get("resolved_ticker") or state.get("ticker")
    if not resolved_ticker:
        logger.error(
            "--- Fundamental Analysis: No resolved ticker available, cannot proceed ---"
        )
        return Command(
            update={
                "current_node": "financial_health",
                "internal_progress": {"financial_health": "error"},
                "error_logs": [
                    {
                        "node": "financial_health",
                        "error": "No resolved ticker available",
                        "severity": "error",
                    }
                ],
            },
            goto=END,
        )

    logger.info(
        f"--- Fundamental Analysis: Fetching financial health data for {resolved_ticker} ---"
    )

    try:
        # Fetch financial data (mult-year)
        financial_reports = fetch_financial_data(resolved_ticker, years=3)

        reports_data = []

        if financial_reports:
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
            years_headers = []
            for r in financial_reports:
                fy = r.base.fiscal_year.value if r.base.fiscal_year else "N/A"
                fp = r.base.fiscal_period.value if r.base.fiscal_period else "N/A"
                years_headers.append(f"{fy} ({fp})")

            headers = ["Metric"] + years_headers

            # --- Base Model Table ---
            base_rows = []
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

            # --- Extension Model Table ---
            first_ext = financial_reports[0].extension if financial_reports else None

            if first_ext:
                ext_rows = []
                ext_metrics = []

                if isinstance(first_ext, IndustrialExtension):
                    ext_metrics = [
                        ("Inventory", "inventory"),
                        ("Accounts Receivable", "accounts_receivable"),
                        ("COGS", "cogs"),
                        ("R&D", "rd_expense"),
                        ("SG&A", "sga_expense"),
                        ("Capex", "capex"),
                    ]
                elif isinstance(first_ext, FinancialServicesExtension):
                    ext_metrics = [
                        ("Loans", "loans_and_leases"),
                        ("Deposits", "deposits"),
                        ("Allowance for Credit Losses", "allowance_for_credit_losses"),
                        ("Interest Income", "interest_income"),
                        ("Interest Expense", "interest_expense"),
                        ("Provision for Loan Losses", "provision_for_loan_losses"),
                    ]
                elif isinstance(first_ext, RealEstateExtension):
                    ext_metrics = [
                        ("Real Estate Assets", "real_estate_assets"),
                        ("Accumulated Dep", "accumulated_depreciation"),
                        ("Dep & Amort", "depreciation_and_amortization"),
                        ("FFO", "ffo"),
                    ]

                for label, attr in ext_metrics:
                    row = [label]
                    for r in financial_reports:
                        ext = r.extension
                        if ext:
                            val = getattr(ext, attr, None)
                            row.append(fmt_currency(val))
                        else:
                            row.append("None")
                    ext_rows.append(row)

            reports_data = [r.model_dump() for r in financial_reports]

            # [NEW] Emit preliminary artifact for real-time UI
            mapper_ctx = {
                "ticker": resolved_ticker,
                "status": "fetching_complete",
                "company_name": resolved_ticker,  # Fallback
            }
            if intent_ctx and "company_profile" in intent_ctx:
                profile = intent_ctx["company_profile"]
                mapper_ctx["company_name"] = profile.get("name")
                mapper_ctx["sector"] = profile.get("sector")
                mapper_ctx["industry"] = profile.get("industry")

            preview = summarize_fundamental_for_preview(mapper_ctx, reports_data)
            artifact = AgentOutputArtifact(
                summary=f"Fundamental Analysis: Data fetched for {resolved_ticker}",
                preview=preview,
                reference=None,
            )
        else:
            logger.warning(
                f"⚠️  Could not fetch financial data for {resolved_ticker}, proceeding without it"
            )
            reports_data = []
            artifact = None

        fa_update = {
            "financial_reports": reports_data,
            "status": "model_selection",
        }
        if artifact:
            fa_update["artifact"] = artifact

    except Exception as e:
        logger.error(f"Financial Health Node Failed: {e}", exc_info=True)
        return Command(
            update={
                "error_logs": [
                    {
                        "node": "financial_health",
                        "error": str(e),
                        "severity": "error",
                    }
                ],
                "internal_progress": {"financial_health": "error"},
                "node_statuses": {"fundamental_analysis": "error"},
            },
            goto=END,
        )

    return Command(
        update={
            "fundamental_analysis": fa_update,
            "current_node": "financial_health",
            "internal_progress": {
                "financial_health": "done",
                "model_selection": "running",
            },
            "node_statuses": {"fundamental_analysis": "running"},
        },
        goto="model_selection",
    )


async def model_selection_node(state: FundamentalAnalysisState) -> Command:
    """
    Select appropriate valuation model based on company profile and financial health.
    """
    try:
        # Get company profile from intent_extraction context
        intent_ctx = state.get("intent_extraction", {})
        profile_data = intent_ctx.get("company_profile")
        profile = CompanyProfile(**profile_data) if profile_data else None
        resolved_ticker = intent_ctx.get("resolved_ticker") or state.get("ticker")

        if not profile:
            logger.warning(
                "--- Fundamental Analysis: Missing company profile, cannot select model ---"
            )
            return Command(
                update={
                    "fundamental_analysis": {"status": "clarifying"},
                    "current_node": "model_selection",
                    "internal_progress": {"model_selection": "waiting"},
                },
                goto="clarifying",
            )

        # Select model based on profile
        model, reasoning = select_valuation_model(profile)

        # Enhance reasoning with financial health insights (using latest report)
        fa_ctx = state.get("fundamental_analysis", {})
        financial_reports = fa_ctx.get("financial_reports")
        if financial_reports:
            try:
                from .financial_models import FinancialReport

                # Use most recent year (index 0)
                latest_report_data = financial_reports[0]
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
                health_context += (
                    f"\n- ROE: {roe_val:.2%}" if roe_val is not None else ""
                )
                health_context += (
                    f"\n- OCF: ${ocf_val:,.0f}" if ocf_val is not None else ""
                )

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

        # [NEW] Generate final artifact
        try:
            mapper_ctx = {
                "ticker": resolved_ticker,
                "status": "done",
                "model_type": model_type,
                "valuation_summary": reasoning,
            }
            if intent_ctx and "company_profile" in intent_ctx:
                profile_data = intent_ctx["company_profile"]
                mapper_ctx["company_name"] = profile_data.get("name")
                mapper_ctx["sector"] = profile_data.get("sector")
                mapper_ctx["industry"] = profile_data.get("industry")

            preview = summarize_fundamental_for_preview(
                mapper_ctx, fa_ctx.get("financial_reports", [])
            )

            # L3: Store full reports in Artifact Store
            full_report_data = {
                "kind": "success",
                "ticker": resolved_ticker,
                "model_type": model_type,
                "company_name": mapper_ctx.get("company_name", resolved_ticker),
                "sector": mapper_ctx.get("sector", "Unknown"),
                "industry": mapper_ctx.get("industry", "Unknown"),
                "reasoning": reasoning,
                "financial_reports": fa_ctx.get("financial_reports", []),
                "status": "done",
            }

            timestamp = int(time.time())
            report_id = await artifact_manager.save_artifact(
                data=full_report_data,
                artifact_type="financial_reports",
                key_prefix=f"fa_{resolved_ticker}_{timestamp}",
            )
            logger.info(
                f"--- [Fundamental Analysis] L3 reports saved (ID: {report_id}) ---"
            )

            reference = None
            if report_id:
                reference = ArtifactReference(
                    artifact_id=report_id,
                    download_url=f"/api/artifacts/{report_id}",
                    type="financial_reports",
                )

            artifact = AgentOutputArtifact(
                summary=f"基本面分析: {preview.get('company_name', resolved_ticker)} ({preview.get('selected_model')})",
                preview=preview,
                reference=reference,
            )
        except Exception as e:
            logger.error(f"Failed to generate artifact in node: {e}")
            artifact = None
            report_id = None

        fa_update = {
            "model_type": model_type,
            "valuation_summary": reasoning,
            "latest_report_id": report_id,
        }
        if artifact:
            fa_update["artifact"] = artifact

    except Exception as e:
        logger.error(f"Model Selection Node Failed: {e}", exc_info=True)
        return Command(
            update={
                "error_logs": [
                    {
                        "node": "model_selection",
                        "error": str(e),
                        "severity": "error",
                    }
                ],
                "internal_progress": {"model_selection": "error"},
                "node_statuses": {"fundamental_analysis": "error"},
            },
            goto=END,
        )

    return Command(
        update={
            "fundamental_analysis": fa_update,
            "ticker": resolved_ticker,  # Keep ticker at top level for global state
            "current_node": "model_selection",
            "internal_progress": {
                "model_selection": "done",
            },
            "node_statuses": {"fundamental_analysis": "done"},
        },
        goto=END,
    )
