from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.fundamental.application.dto import FundamentalAppContextDTO
from src.agents.fundamental.application.fundamental_service import (
    build_and_store_model_selection_artifact,
    build_valuation_error_update,
    build_valuation_missing_inputs_update,
    build_valuation_success_update,
    enrich_reasoning_with_health_context,
)
from src.agents.fundamental.application.state_readers import (
    read_fundamental_state,
    read_intent_state,
)
from src.agents.fundamental.application.state_updates import (
    build_financial_health_missing_ticker_update,
    build_financial_health_success_update,
    build_model_selection_success_update,
    build_model_selection_waiting_update,
    build_node_error_update,
)
from src.agents.fundamental.data.mappers import project_selection_reports
from src.agents.fundamental.data.ports import FundamentalArtifactPort
from src.agents.fundamental.domain.entities import FundamentalSelectionReport
from src.agents.fundamental.domain.services import resolve_calculator_model_type
from src.agents.fundamental.domain.valuation.param_builder import ParamBuildResult
from src.agents.fundamental.interface.mappers import (
    build_mapper_context as build_fundamental_mapper_context,
)
from src.agents.fundamental.interface.parsers import (
    parse_calculation_metrics,
    parse_valuation_skill_runtime,
)
from src.agents.fundamental.interface.serializers import (
    serialize_model_selection_details,
)
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.tools.logger import get_logger
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject

logger = get_logger(__name__)


@dataclass(frozen=True)
class FundamentalNodeResult:
    update: dict[str, object]
    goto: str


@dataclass(frozen=True)
class FundamentalOrchestrator:
    port: FundamentalArtifactPort
    summarize_preview: Callable[
        [FundamentalAppContextDTO, list[JSONObject] | None], JSONObject
    ]
    build_progress_artifact: Callable[[str, JSONObject], AgentOutputArtifactPayload]
    normalize_model_selection_reports: Callable[[list[JSONObject]], list[JSONObject]]
    build_model_selection_report_payload: Callable[
        [str, str, str, str, str, str, list[JSONObject]], JSONObject
    ]
    build_model_selection_artifact: Callable[
        [str, str, JSONObject], AgentOutputArtifactPayload
    ]
    build_valuation_artifact: Callable[
        [str | None, str, str, JSONObject], AgentOutputArtifactPayload
    ]

    async def save_financial_reports(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.port.save_financial_reports(
            data=data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_financial_reports(self, artifact_id: str) -> list[JSONObject] | None:
        return await self.port.load_financial_reports(artifact_id)

    def enrich_reasoning_with_health_context(
        self,
        reasoning: str,
        financial_reports: list[FundamentalSelectionReport],
    ) -> str:
        return enrich_reasoning_with_health_context(reasoning, financial_reports)

    async def build_and_store_model_selection_artifact(
        self,
        *,
        intent_ctx: dict[str, object],
        resolved_ticker: str | None,
        model_type: str,
        reasoning: str,
        financial_reports: list[JSONObject],
    ) -> tuple[AgentOutputArtifactPayload | None, str | None]:
        return await build_and_store_model_selection_artifact(
            intent_ctx=intent_ctx,
            resolved_ticker=resolved_ticker,
            model_type=model_type,
            reasoning=reasoning,
            financial_reports=financial_reports,
            port=self.port,
            summarize_preview=self.summarize_preview,
            normalize_model_selection_reports_fn=self.normalize_model_selection_reports,
            build_model_selection_report_payload_fn=self.build_model_selection_report_payload,
            build_model_selection_artifact_fn=self.build_model_selection_artifact,
        )

    def build_valuation_missing_inputs_update(
        self,
        *,
        fundamental: dict[str, object],
        missing_inputs: list[str],
        assumptions: list[str],
    ) -> JSONObject:
        return build_valuation_missing_inputs_update(
            fundamental=fundamental,
            missing_inputs=missing_inputs,
            assumptions=assumptions,
        )

    def build_valuation_success_update(
        self,
        *,
        fundamental: dict[str, object],
        intent_ctx: dict[str, object],
        ticker: str | None,
        model_type: str,
        reports_raw: list[JSONObject],
        reports_artifact_id: str,
        params_dump: JSONObject,
        calculation_metrics: JSONObject,
        assumptions: list[str],
    ) -> JSONObject:
        return build_valuation_success_update(
            fundamental=fundamental,
            intent_ctx=intent_ctx,
            ticker=ticker,
            model_type=model_type,
            reports_raw=reports_raw,
            reports_artifact_id=reports_artifact_id,
            params_dump=params_dump,
            calculation_metrics=calculation_metrics,
            assumptions=assumptions,
            summarize_preview=self.summarize_preview,
            build_valuation_artifact_fn=self.build_valuation_artifact,
        )

    def build_valuation_error_update(self, error: str) -> JSONObject:
        return build_valuation_error_update(error)

    async def run_financial_health(
        self,
        state: Mapping[str, object],
        *,
        fetch_financial_data_fn: Callable[[str], object],
        normalize_financial_reports_fn: Callable[[object, str], list[JSONObject]],
    ) -> FundamentalNodeResult:
        intent_state = read_intent_state(state)
        resolved_ticker = intent_state.resolved_ticker
        if resolved_ticker is None:
            logger.error(
                "--- Fundamental Analysis: No resolved ticker available, cannot proceed ---"
            )
            return FundamentalNodeResult(
                update=build_financial_health_missing_ticker_update(),
                goto="END",
            )

        logger.info(
            "--- Fundamental Analysis: Fetching financial health data for %s ---",
            resolved_ticker,
        )
        try:
            financial_reports_raw = fetch_financial_data_fn(resolved_ticker)
            reports_data: list[JSONObject] = []
            reports_artifact_id: str | None = None
            artifact: AgentOutputArtifactPayload | None = None

            if financial_reports_raw:
                reports_data = normalize_financial_reports_fn(
                    financial_reports_raw, "financial_health.financial_reports"
                )
                reports_artifact_id = await self.save_financial_reports(
                    data={"financial_reports": reports_data},
                    produced_by="fundamental_analysis.financial_health",
                    key_prefix=f"fa_reports_{resolved_ticker}",
                )
                mapper_ctx = build_fundamental_mapper_context(
                    intent_state.context,
                    resolved_ticker,
                    status="fetching_complete",
                )
                preview = self.summarize_preview(mapper_ctx, reports_data)
                artifact = self.build_progress_artifact(
                    f"Fundamental Analysis: Data fetched for {resolved_ticker}",
                    preview,
                )
            else:
                logger.warning(
                    "Could not fetch financial data for %s, proceeding without it",
                    resolved_ticker,
                )

            return FundamentalNodeResult(
                update=build_financial_health_success_update(
                    reports_artifact_id=reports_artifact_id,
                    artifact=artifact,
                ),
                goto="model_selection",
            )
        except Exception as exc:
            logger.error("Financial Health Node Failed: %s", exc, exc_info=True)
            return FundamentalNodeResult(
                update=build_node_error_update(
                    node="financial_health",
                    error=str(exc),
                ),
                goto="END",
            )

    async def run_model_selection(
        self,
        state: Mapping[str, object],
        *,
        select_valuation_model_fn: Callable[
            [CompanyProfile, list[FundamentalSelectionReport]], object
        ],
    ) -> FundamentalNodeResult:
        try:
            intent_state = read_intent_state(state)
            profile = intent_state.profile
            resolved_ticker = intent_state.resolved_ticker

            if profile is None:
                logger.warning(
                    "--- Fundamental Analysis: Missing company profile, cannot select model ---"
                )
                return FundamentalNodeResult(
                    update=build_model_selection_waiting_update(),
                    goto="clarifying",
                )

            fundamental_state = read_fundamental_state(state)
            reports_artifact_id = fundamental_state.financial_reports_artifact_id
            financial_reports: list[JSONObject] = []
            selection_reports: list[FundamentalSelectionReport] = []
            if reports_artifact_id is not None:
                loaded_reports = await self.load_financial_reports(reports_artifact_id)
                if loaded_reports is not None:
                    selection_reports = project_selection_reports(loaded_reports)
                    financial_reports = loaded_reports

            selection = select_valuation_model_fn(profile, selection_reports)
            model = selection.model
            reasoning = selection.reasoning

            if financial_reports:
                reasoning = self.enrich_reasoning_with_health_context(
                    reasoning,
                    selection_reports,
                )

            selection_details = serialize_model_selection_details(selection)
            model_type = resolve_calculator_model_type(model.value)

            artifact: AgentOutputArtifactPayload | None
            report_id: str | None
            try:
                (
                    artifact,
                    report_id,
                ) = await self.build_and_store_model_selection_artifact(
                    intent_ctx=intent_state.context,
                    resolved_ticker=resolved_ticker,
                    model_type=model_type,
                    reasoning=reasoning,
                    financial_reports=financial_reports,
                )
            except Exception as exc:
                logger.error("Failed to generate model selection artifact: %s", exc)
                artifact, report_id = None, None

            fa_update: JSONObject = {
                "model_type": model_type,
                "selected_model": model.value,
                "valuation_summary": reasoning,
                "financial_reports_artifact_id": report_id or reports_artifact_id,
                "model_selection_details": selection_details,
            }
            if artifact is not None:
                fa_update["artifact"] = artifact

            return FundamentalNodeResult(
                update=build_model_selection_success_update(
                    fa_update=fa_update,
                    resolved_ticker=resolved_ticker,
                ),
                goto="calculation",
            )
        except Exception as exc:
            logger.error("Model Selection Node Failed: %s", exc, exc_info=True)
            return FundamentalNodeResult(
                update=build_node_error_update(
                    node="model_selection",
                    error=str(exc),
                ),
                goto="END",
            )

    async def run_valuation(
        self,
        state: Mapping[str, object],
        *,
        build_params_fn: Callable[
            [str, str | None, list[JSONObject]], ParamBuildResult
        ],
        get_skill_fn: Callable[[str], object | None],
    ) -> FundamentalNodeResult:
        logger.info("--- Fundamental Analysis: Running valuation calculation ---")
        try:
            fundamental_state = read_fundamental_state(state)
            fundamental = fundamental_state.context
            model_type = fundamental_state.model_type
            intent_state = read_intent_state(state)
            intent_ctx = intent_state.context
            ticker = intent_state.resolved_ticker

            if model_type is None:
                raise ValueError("Missing model_type for valuation calculation")

            skill_runtime = parse_valuation_skill_runtime(
                get_skill_fn(model_type),
                context=f"valuation skill runtime for {model_type}",
            )
            schema = skill_runtime.schema
            calc_func = skill_runtime.calculator

            reports_artifact_id = fundamental_state.financial_reports_artifact_id
            if reports_artifact_id is None:
                raise ValueError("Missing financial_reports_artifact_id for valuation")

            reports_raw = await self.load_financial_reports(reports_artifact_id)
            if reports_raw is None:
                raise ValueError(
                    "Missing financial reports artifact data for valuation"
                )
            if not reports_raw:
                raise ValueError("Empty financial reports data for valuation")

            build_result = build_params_fn(model_type, ticker, reports_raw)

            if build_result.assumptions:
                logger.warning(
                    "Controlled assumptions applied for %s: %s",
                    model_type,
                    "; ".join(build_result.assumptions),
                )

            if build_result.missing:
                logger.error(
                    "--- Fundamental Analysis: Missing valuation inputs for ticker=%s model=%s missing=%s assumptions=%s ---",
                    ticker or "unknown",
                    model_type,
                    ", ".join(build_result.missing),
                    "; ".join(build_result.assumptions)
                    if build_result.assumptions
                    else "none",
                )
                return FundamentalNodeResult(
                    update=self.build_valuation_missing_inputs_update(
                        fundamental=dict(fundamental),
                        missing_inputs=build_result.missing,
                        assumptions=build_result.assumptions,
                    ),
                    goto="END",
                )

            params_dict = dict(build_result.params)
            params_dict["trace_inputs"] = build_result.trace_inputs

            params_obj = schema(**params_dict)
            params_dump = params_obj.model_dump(mode="json")
            if not isinstance(params_dump, dict):
                raise TypeError("valuation params must serialize to JSON object")
            result = parse_calculation_metrics(
                calc_func(params_obj),
                context=f"{model_type} valuation calculation result",
            )

            return FundamentalNodeResult(
                update=self.build_valuation_success_update(
                    fundamental=dict(fundamental),
                    intent_ctx=intent_ctx,
                    ticker=ticker,
                    model_type=model_type,
                    reports_raw=reports_raw,
                    reports_artifact_id=reports_artifact_id,
                    params_dump=params_dump,
                    calculation_metrics=result,
                    assumptions=build_result.assumptions,
                ),
                goto="END",
            )
        except Exception as exc:
            logger.error("Valuation Node Failed: %s", exc, exc_info=True)
            return FundamentalNodeResult(
                update=self.build_valuation_error_update(str(exc)),
                goto="END",
            )
