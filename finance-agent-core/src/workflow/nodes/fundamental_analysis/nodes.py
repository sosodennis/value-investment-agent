from langgraph.graph import END
from langgraph.types import Command

from src.agents.fundamental.application.services import (
    build_and_store_model_selection_artifact,
    build_mapper_context,
    build_selection_details,
    build_valuation_error_update,
    build_valuation_missing_inputs_update,
    build_valuation_success_update,
    enrich_reasoning_with_health_context,
)
from src.agents.fundamental.data.ports import fundamental_artifact_port
from src.agents.fundamental.interface.mappers import summarize_fundamental_for_preview
from src.common.contracts import (
    OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
)
from src.common.tools.logger import get_logger
from src.common.types import JSONObject
from src.interface.canonical_serializers import (
    normalize_financial_reports,
)
from src.interface.schemas import build_artifact_payload

from .structures import CompanyProfile, ValuationModel
from .subgraph_state import FundamentalAnalysisState
from .tools.model_selection import select_valuation_model
from .tools.sec_xbrl.utils import fetch_financial_data
from .tools.valuation.param_builder import build_params
from .tools.valuation.registry import SkillRegistry

logger = get_logger(__name__)


async def financial_health_node(state: FundamentalAnalysisState) -> Command:
    """
    Fetch financial data from SEC EDGAR and generate Financial Health Report.
    """
    # Get resolved ticker from intent_extraction context
    intent_ctx = state.get("intent_extraction", {})
    resolved_ticker = intent_ctx.get("resolved_ticker")
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
            logger.info(
                f"✅ Generated {len(financial_reports)} Financial Health Reports for {resolved_ticker}"
            )

            reports_data = normalize_financial_reports(
                financial_reports, "financial_health.financial_reports"
            )
            reports_artifact_id = (
                await fundamental_artifact_port.save_financial_reports(
                    data={"financial_reports": reports_data},
                    produced_by="fundamental_analysis.financial_health",
                    key_prefix=f"fa_reports_{resolved_ticker}",
                )
            )

            # [NEW] Emit preliminary artifact for real-time UI
            mapper_ctx = build_mapper_context(
                intent_ctx,
                resolved_ticker,
                status="fetching_complete",
            )

            preview = summarize_fundamental_for_preview(mapper_ctx, reports_data)
            artifact = build_artifact_payload(
                kind=OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
                summary=f"Fundamental Analysis: Data fetched for {resolved_ticker}",
                preview=preview,
                reference=None,
            )
        else:
            logger.warning(
                f"⚠️  Could not fetch financial data for {resolved_ticker}, proceeding without it"
            )
            reports_data = []
            reports_artifact_id = None
            artifact = None

        fa_update = {
            "financial_reports_artifact_id": reports_artifact_id,
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
        resolved_ticker = intent_ctx.get("resolved_ticker")

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

        # Select model based on profile and available financial reports
        fa_ctx = state.get("fundamental_analysis", {})
        reports_artifact_id = fa_ctx.get("financial_reports_artifact_id")
        financial_reports: list[JSONObject] = []
        if reports_artifact_id:
            artifact_reports = await fundamental_artifact_port.load_financial_reports(
                reports_artifact_id
            )
            if artifact_reports is not None:
                financial_reports = artifact_reports

        selection = select_valuation_model(profile, financial_reports)
        model = selection.model
        reasoning = selection.reasoning

        # Enhance reasoning with financial health insights (using latest report)
        if financial_reports:
            try:
                reasoning = enrich_reasoning_with_health_context(
                    reasoning,
                    financial_reports,
                    port=fundamental_artifact_port,
                )
            except Exception as e:
                logger.warning(f"⚠️  Could not parse financial report for insights: {e}")

        # Capture model selection details for auditability
        selection_details = build_selection_details(selection)

        # Map selected valuation model to calculator skill key
        model_type_map = {
            ValuationModel.DCF_GROWTH: "saas",
            ValuationModel.DCF_STANDARD: "saas",
            ValuationModel.DDM: "bank",
            ValuationModel.FFO: "reit_ffo",
            ValuationModel.EV_REVENUE: "ev_revenue",
            ValuationModel.EV_EBITDA: "ev_ebitda",
            ValuationModel.RESIDUAL_INCOME: "residual_income",
            ValuationModel.EVA: "eva",
        }
        model_type = model_type_map.get(model, "saas")

        # [NEW] Generate final artifact
        try:
            artifact, report_id = await build_and_store_model_selection_artifact(
                intent_ctx=intent_ctx,
                resolved_ticker=resolved_ticker,
                model_type=model_type,
                reasoning=reasoning,
                financial_reports=financial_reports,
                port=fundamental_artifact_port,
                summarize_preview=summarize_fundamental_for_preview,
            )
            logger.info(
                f"--- [Fundamental Analysis] L3 reports saved (ID: {report_id}) ---"
            )
        except Exception as e:
            logger.error(f"Failed to generate artifact in node: {e}")
            artifact = None
            report_id = None

        fa_update = {
            "model_type": model_type,
            "selected_model": model.value,
            "valuation_summary": reasoning,
            "financial_reports_artifact_id": report_id or reports_artifact_id,
            "model_selection_details": selection_details,
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
                "calculation": "running",
            },
            "node_statuses": {"fundamental_analysis": "running"},
        },
        goto="calculation",
    )


async def valuation_node(state: FundamentalAnalysisState) -> Command:
    """
    Executes deterministic valuation calculations inside Fundamental Analysis.
    Uses in-node deterministic calculator path.
    """
    logger.info("--- Fundamental Analysis: Running valuation calculation ---")

    try:
        fundamental = state.get("fundamental_analysis", {})
        model_type = fundamental.get("model_type")
        intent_ctx = state.get("intent_extraction", {})
        ticker = intent_ctx.get("resolved_ticker")

        if not model_type:
            raise ValueError("Missing model_type for valuation calculation")

        skill = SkillRegistry.get_skill(model_type)
        if not skill:
            raise ValueError(f"Skill not found for model type: {model_type}")

        schema = skill["schema"]
        calc_func = skill["calculator"]

        reports_raw: list[JSONObject] = []
        reports_artifact_id = fundamental.get("financial_reports_artifact_id")
        if not reports_artifact_id:
            raise ValueError("Missing financial_reports_artifact_id for valuation")
        reports_raw_data = await fundamental_artifact_port.load_financial_reports(
            reports_artifact_id
        )
        if reports_raw_data is None:
            raise ValueError("Missing financial reports artifact data for valuation")
        reports_raw = reports_raw_data
        if not reports_raw:
            raise ValueError("Empty financial reports data for valuation")
        build_result = build_params(model_type, ticker, reports_raw)

        if build_result.assumptions:
            logger.warning(
                "Controlled assumptions applied for %s: %s",
                model_type,
                "; ".join(build_result.assumptions),
            )

        if build_result.missing:
            logger.error(
                f"Missing SEC XBRL inputs for {model_type}: {', '.join(build_result.missing)}"
            )
            return Command(
                update=build_valuation_missing_inputs_update(
                    fundamental=fundamental,
                    missing_inputs=build_result.missing,
                    assumptions=build_result.assumptions,
                ),
                goto=END,
            )

        params_dict = build_result.params
        params_dict["trace_inputs"] = build_result.trace_inputs

        params_obj = schema(**params_dict)
        result = calc_func(params_obj)

        return Command(
            update=build_valuation_success_update(
                fundamental=fundamental,
                intent_ctx=intent_ctx,
                ticker=ticker,
                model_type=model_type,
                reports_raw=reports_raw,
                reports_artifact_id=reports_artifact_id,
                params_dump=params_obj.model_dump(mode="json"),
                calculation_metrics=result,
                assumptions=build_result.assumptions,
                summarize_preview=summarize_fundamental_for_preview,
            ),
            goto=END,
        )
    except Exception as e:
        logger.error(f"Valuation Node Failed: {e}", exc_info=True)
        return Command(
            update=build_valuation_error_update(str(e)),
            goto=END,
        )
