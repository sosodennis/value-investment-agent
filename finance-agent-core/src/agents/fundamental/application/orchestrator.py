from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.fundamental.application import use_cases
from src.agents.fundamental.data.ports import (
    FundamentalArtifactPort,
    fundamental_artifact_port,
)
from src.agents.fundamental.interface.mappers import summarize_fundamental_for_preview
from src.common.contracts import OUTPUT_KIND_FUNDAMENTAL_ANALYSIS
from src.common.tools.logger import get_logger
from src.common.types import AgentOutputArtifactPayload, JSONObject
from src.interface.schemas import build_artifact_payload
from src.shared.domain.market_identity import CompanyProfile

logger = get_logger(__name__)


@dataclass(frozen=True)
class FundamentalNodeResult:
    update: dict[str, object]
    goto: str


@dataclass(frozen=True)
class FundamentalOrchestrator:
    port: FundamentalArtifactPort
    summarize_preview: Callable[[dict[str, object], list[JSONObject]], JSONObject]

    def build_mapper_context(
        self,
        intent_ctx: dict[str, object],
        resolved_ticker: str | None,
        *,
        status: str,
        model_type: str | None = None,
        valuation_summary: str | None = None,
    ) -> dict[str, object]:
        return use_cases.build_mapper_context(
            intent_ctx,
            resolved_ticker,
            status=status,
            model_type=model_type,
            valuation_summary=valuation_summary,
        )

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

    def build_selection_details(
        self, selection: use_cases._ModelSelectionLike
    ) -> dict[str, object]:
        return use_cases.build_selection_details(selection)

    def enrich_reasoning_with_health_context(
        self,
        reasoning: str,
        financial_reports: list[JSONObject],
    ) -> str:
        return use_cases.enrich_reasoning_with_health_context(
            reasoning, financial_reports
        )

    async def build_and_store_model_selection_artifact(
        self,
        *,
        intent_ctx: dict[str, object],
        resolved_ticker: str | None,
        model_type: str,
        reasoning: str,
        financial_reports: list[JSONObject],
    ) -> tuple[AgentOutputArtifactPayload | None, str | None]:
        return await use_cases.build_and_store_model_selection_artifact(
            intent_ctx=intent_ctx,
            resolved_ticker=resolved_ticker,
            model_type=model_type,
            reasoning=reasoning,
            financial_reports=financial_reports,
            port=self.port,
            summarize_preview=self.summarize_preview,
        )

    def resolve_selection_model_type(self, selected_model_value: str) -> str:
        return use_cases.resolve_selection_model_type(selected_model_value)

    def build_valuation_missing_inputs_update(
        self,
        *,
        fundamental: dict[str, object],
        missing_inputs: list[str],
        assumptions: list[str],
    ) -> JSONObject:
        return use_cases.build_valuation_missing_inputs_update(
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
        return use_cases.build_valuation_success_update(
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
        )

    def build_valuation_error_update(self, error: str) -> JSONObject:
        return use_cases.build_valuation_error_update(error)

    async def run_financial_health(
        self,
        state: Mapping[str, object],
        *,
        fetch_financial_data_fn: Callable[[str], object],
        normalize_financial_reports_fn: Callable[[object, str], list[JSONObject]],
    ) -> FundamentalNodeResult:
        intent_ctx_raw = state.get("intent_extraction", {})
        intent_ctx = intent_ctx_raw if isinstance(intent_ctx_raw, Mapping) else {}
        resolved_ticker = intent_ctx.get("resolved_ticker")
        if not isinstance(resolved_ticker, str) or not resolved_ticker:
            logger.error(
                "--- Fundamental Analysis: No resolved ticker available, cannot proceed ---"
            )
            return FundamentalNodeResult(
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
                mapper_ctx = self.build_mapper_context(
                    dict(intent_ctx),
                    resolved_ticker,
                    status="fetching_complete",
                )
                preview = self.summarize_preview(mapper_ctx, reports_data)
                artifact = build_artifact_payload(
                    kind=OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
                    summary=f"Fundamental Analysis: Data fetched for {resolved_ticker}",
                    preview=preview,
                    reference=None,
                )
            else:
                logger.warning(
                    "Could not fetch financial data for %s, proceeding without it",
                    resolved_ticker,
                )

            fa_update: JSONObject = {
                "financial_reports_artifact_id": reports_artifact_id,
                "status": "model_selection",
            }
            if artifact is not None:
                fa_update["artifact"] = artifact

            return FundamentalNodeResult(
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
        except Exception as exc:
            logger.error("Financial Health Node Failed: %s", exc, exc_info=True)
            return FundamentalNodeResult(
                update={
                    "error_logs": [
                        {
                            "node": "financial_health",
                            "error": str(exc),
                            "severity": "error",
                        }
                    ],
                    "internal_progress": {"financial_health": "error"},
                    "node_statuses": {"fundamental_analysis": "error"},
                },
                goto="END",
            )

    async def run_model_selection(
        self,
        state: Mapping[str, object],
        *,
        select_valuation_model_fn: Callable[[CompanyProfile, list[JSONObject]], object],
    ) -> FundamentalNodeResult:
        try:
            intent_ctx_raw = state.get("intent_extraction", {})
            intent_ctx = intent_ctx_raw if isinstance(intent_ctx_raw, Mapping) else {}
            profile_data = intent_ctx.get("company_profile")
            profile = (
                CompanyProfile(**profile_data)
                if isinstance(profile_data, Mapping)
                else None
            )
            resolved_ticker = intent_ctx.get("resolved_ticker")

            if profile is None:
                logger.warning(
                    "--- Fundamental Analysis: Missing company profile, cannot select model ---"
                )
                return FundamentalNodeResult(
                    update={
                        "fundamental_analysis": {"status": "clarifying"},
                        "current_node": "model_selection",
                        "internal_progress": {"model_selection": "waiting"},
                    },
                    goto="clarifying",
                )

            fa_ctx_raw = state.get("fundamental_analysis", {})
            fa_ctx = fa_ctx_raw if isinstance(fa_ctx_raw, Mapping) else {}
            reports_artifact_id = fa_ctx.get("financial_reports_artifact_id")
            financial_reports: list[JSONObject] = []
            if isinstance(reports_artifact_id, str) and reports_artifact_id:
                loaded = await self.load_financial_reports(reports_artifact_id)
                if loaded is not None:
                    financial_reports = loaded

            selection = select_valuation_model_fn(profile, financial_reports)
            model = selection.model
            reasoning = selection.reasoning

            if financial_reports:
                reasoning = self.enrich_reasoning_with_health_context(
                    reasoning,
                    financial_reports,
                )

            selection_details = self.build_selection_details(selection)
            model_type = self.resolve_selection_model_type(model.value)

            artifact: AgentOutputArtifactPayload | None
            report_id: str | None
            try:
                (
                    artifact,
                    report_id,
                ) = await self.build_and_store_model_selection_artifact(
                    intent_ctx=dict(intent_ctx),
                    resolved_ticker=resolved_ticker
                    if isinstance(resolved_ticker, str)
                    else None,
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
                update={
                    "fundamental_analysis": fa_update,
                    "ticker": resolved_ticker,
                    "current_node": "model_selection",
                    "internal_progress": {
                        "model_selection": "done",
                        "calculation": "running",
                    },
                    "node_statuses": {"fundamental_analysis": "running"},
                },
                goto="calculation",
            )
        except Exception as exc:
            logger.error("Model Selection Node Failed: %s", exc, exc_info=True)
            return FundamentalNodeResult(
                update={
                    "error_logs": [
                        {
                            "node": "model_selection",
                            "error": str(exc),
                            "severity": "error",
                        }
                    ],
                    "internal_progress": {"model_selection": "error"},
                    "node_statuses": {"fundamental_analysis": "error"},
                },
                goto="END",
            )

    async def run_valuation(
        self,
        state: Mapping[str, object],
        *,
        build_params_fn: Callable[[str, object, list[JSONObject]], object],
        get_skill_fn: Callable[[object], object | None],
    ) -> FundamentalNodeResult:
        logger.info("--- Fundamental Analysis: Running valuation calculation ---")
        try:
            fundamental_raw = state.get("fundamental_analysis", {})
            fundamental = (
                fundamental_raw if isinstance(fundamental_raw, Mapping) else {}
            )
            model_type = fundamental.get("model_type")
            intent_ctx_raw = state.get("intent_extraction", {})
            intent_ctx = intent_ctx_raw if isinstance(intent_ctx_raw, Mapping) else {}
            ticker = intent_ctx.get("resolved_ticker")

            if not isinstance(model_type, str) or not model_type:
                raise ValueError("Missing model_type for valuation calculation")

            skill = get_skill_fn(model_type)
            if not isinstance(skill, Mapping):
                raise ValueError(f"Skill not found for model type: {model_type}")

            schema = skill["schema"]
            calc_func = skill["calculator"]

            reports_artifact_id = fundamental.get("financial_reports_artifact_id")
            if not isinstance(reports_artifact_id, str) or not reports_artifact_id:
                raise ValueError("Missing financial_reports_artifact_id for valuation")

            reports_raw_data = await self.load_financial_reports(reports_artifact_id)
            if reports_raw_data is None:
                raise ValueError(
                    "Missing financial reports artifact data for valuation"
                )
            reports_raw = reports_raw_data
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
                return FundamentalNodeResult(
                    update=self.build_valuation_missing_inputs_update(
                        fundamental=dict(fundamental),
                        missing_inputs=build_result.missing,
                        assumptions=build_result.assumptions,
                    ),
                    goto="END",
                )

            params_dict = build_result.params
            params_dict["trace_inputs"] = build_result.trace_inputs

            params_obj = schema(**params_dict)
            result = calc_func(params_obj)

            return FundamentalNodeResult(
                update=self.build_valuation_success_update(
                    fundamental=dict(fundamental),
                    intent_ctx=dict(intent_ctx),
                    ticker=ticker if isinstance(ticker, str) else None,
                    model_type=model_type,
                    reports_raw=reports_raw,
                    reports_artifact_id=reports_artifact_id,
                    params_dump=params_obj.model_dump(mode="json"),
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


fundamental_orchestrator = FundamentalOrchestrator(
    port=fundamental_artifact_port,
    summarize_preview=summarize_fundamental_for_preview,
)
