from __future__ import annotations

import logging
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
from src.agents.fundamental.data.mappers import (
    financial_report_models_to_json,
    project_selection_reports,
)
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
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)


FundamentalNodeResult = WorkflowNodeResult


def _normalize_forward_signals(raw: object) -> list[JSONObject] | None:
    if not isinstance(raw, list):
        return None
    normalized: list[JSONObject] = []
    for item in raw:
        if isinstance(item, Mapping):
            normalized.append(dict(item))
    return normalized or None


def _extract_financial_health_payload(
    raw: object,
) -> tuple[object, list[JSONObject] | None]:
    if not isinstance(raw, Mapping):
        return raw, None

    reports_raw = raw.get("financial_reports")
    if reports_raw is None:
        reports_raw = raw.get("reports")
    if reports_raw is None:
        reports_raw = []

    forward_signals = _normalize_forward_signals(raw.get("forward_signals"))
    return reports_raw, forward_signals


def _extract_distribution_summary_for_logging(
    calculation_metrics: Mapping[str, object],
) -> Mapping[str, object] | None:
    direct = calculation_metrics.get("distribution_summary")
    if isinstance(direct, Mapping):
        return direct

    details = calculation_metrics.get("details")
    if isinstance(details, Mapping):
        nested = details.get("distribution_summary")
        if isinstance(nested, Mapping):
            return nested

    return None


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return bool(value)
    return None


def _coerce_non_negative_int(value: object) -> int | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        parsed = int(value)
        return parsed if parsed >= 0 else 0
    return None


def _build_monte_carlo_completion_fields(
    calculation_metrics: Mapping[str, object],
) -> dict[str, object]:
    fields: dict[str, object] = {
        "sampler_type": "disabled",
        "executed_iterations": 0,
        "corr_diagnostics_available": False,
        "psd_repaired": False,
    }

    distribution_summary = _extract_distribution_summary_for_logging(
        calculation_metrics
    )
    if distribution_summary is None:
        return fields

    diagnostics = distribution_summary.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        return fields

    sampler_type = diagnostics.get("sampler_type")
    if isinstance(sampler_type, str) and sampler_type:
        fields["sampler_type"] = sampler_type

    executed_iterations = _coerce_non_negative_int(
        diagnostics.get("executed_iterations")
    )
    if executed_iterations is not None:
        fields["executed_iterations"] = executed_iterations

    corr_diagnostics = _coerce_bool(diagnostics.get("corr_diagnostics_available"))
    if corr_diagnostics is not None:
        fields["corr_diagnostics_available"] = corr_diagnostics

    psd_repaired = _coerce_bool(diagnostics.get("psd_repaired"))
    if psd_repaired is not None:
        fields["psd_repaired"] = psd_repaired

    return fields


def _normalize_source_types(raw: object) -> list[str]:
    if not isinstance(raw, list | tuple):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def _build_forward_signal_completion_fields(
    *,
    forward_signals: list[JSONObject] | None,
    build_metadata: Mapping[str, object] | None,
) -> dict[str, object]:
    raw_count = len(forward_signals or [])
    count = raw_count
    source_types: list[str] = []

    if isinstance(build_metadata, Mapping):
        forward_signal_raw = build_metadata.get("forward_signal")
        if isinstance(forward_signal_raw, Mapping):
            parsed_count = _coerce_non_negative_int(
                forward_signal_raw.get("signals_total")
            )
            if parsed_count is not None:
                count = parsed_count
            parsed_sources = _normalize_source_types(
                forward_signal_raw.get("source_types")
            )
            if parsed_sources:
                source_types = parsed_sources

    if not source_types and isinstance(forward_signals, list):
        source_types = _normalize_source_types(
            [
                item.get("source_type")
                for item in forward_signals
                if isinstance(item, Mapping)
            ]
        )

    source_label = ",".join(source_types) if source_types else "none"
    present = raw_count > 0 or count > 0
    return {
        "forward_signals_present": present,
        "forward_signals_count": count,
        "forward_signals_source": source_label,
    }


@dataclass(frozen=True)
class FundamentalOrchestrator:
    port: FundamentalArtifactPort
    summarize_preview: Callable[
        [FundamentalAppContextDTO, list[JSONObject] | None], JSONObject
    ]
    build_progress_artifact: Callable[[str, JSONObject], AgentOutputArtifactPayload]
    normalize_model_selection_reports: Callable[[list[JSONObject]], list[JSONObject]]
    build_model_selection_report_payload: Callable[
        [str, str, str, str, str, str, list[JSONObject], list[JSONObject] | None],
        JSONObject,
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

    async def load_financial_reports_bundle(
        self, artifact_id: str
    ) -> tuple[list[JSONObject], list[JSONObject] | None] | None:
        payload = await self.port.load_financial_reports_payload(artifact_id)
        if payload is None:
            return None
        reports_raw = financial_report_models_to_json(payload.financial_reports)
        forward_signals = _normalize_forward_signals(payload.forward_signals)
        return reports_raw, forward_signals

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
        forward_signals: list[JSONObject] | None,
    ) -> tuple[AgentOutputArtifactPayload | None, str | None]:
        return await build_and_store_model_selection_artifact(
            intent_ctx=intent_ctx,
            resolved_ticker=resolved_ticker,
            model_type=model_type,
            reasoning=reasoning,
            financial_reports=financial_reports,
            forward_signals=forward_signals,
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
        build_metadata: JSONObject | None = None,
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
            build_metadata=build_metadata,
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
            log_event(
                logger,
                event="fundamental_financial_health_missing_ticker",
                message="fundamental financial health missing resolved ticker",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_TICKER_MISSING",
            )
            return FundamentalNodeResult(
                update=build_financial_health_missing_ticker_update(),
                goto="END",
            )

        log_event(
            logger,
            event="fundamental_financial_health_started",
            message="fundamental financial health started",
            fields={"ticker": resolved_ticker},
        )
        try:
            financial_reports_raw = fetch_financial_data_fn(resolved_ticker)
            (
                reports_input,
                forward_signals,
            ) = _extract_financial_health_payload(financial_reports_raw)
            reports_data: list[JSONObject] = []
            reports_artifact_id: str | None = None
            artifact: AgentOutputArtifactPayload | None = None

            if reports_input:
                reports_data = normalize_financial_reports_fn(
                    reports_input, "financial_health.financial_reports"
                )
                artifact_payload: JSONObject = {"financial_reports": reports_data}
                if isinstance(forward_signals, list):
                    artifact_payload["forward_signals"] = forward_signals
                reports_artifact_id = await self.save_financial_reports(
                    data=artifact_payload,
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
                log_event(
                    logger,
                    event="fundamental_financial_health_empty_reports",
                    message="financial health reports unavailable; continuing without reports",
                    level=logging.WARNING,
                    error_code="FUNDAMENTAL_REPORTS_UNAVAILABLE",
                    fields={"ticker": resolved_ticker},
                )

            return FundamentalNodeResult(
                update=build_financial_health_success_update(
                    reports_artifact_id=reports_artifact_id,
                    artifact=artifact,
                ),
                goto="model_selection",
            )
        except Exception as exc:
            log_event(
                logger,
                event="fundamental_financial_health_failed",
                message="fundamental financial health failed",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_FINANCIAL_HEALTH_FAILED",
                fields={"exception": str(exc), "ticker": resolved_ticker},
            )
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
                log_event(
                    logger,
                    event="fundamental_model_selection_profile_missing",
                    message="fundamental model selection missing company profile",
                    level=logging.WARNING,
                    error_code="FUNDAMENTAL_PROFILE_MISSING",
                    fields={"ticker": resolved_ticker},
                )
                return FundamentalNodeResult(
                    update=build_model_selection_waiting_update(),
                    goto="clarifying",
                )

            fundamental_state = read_fundamental_state(state)
            reports_artifact_id = fundamental_state.financial_reports_artifact_id
            financial_reports: list[JSONObject] = []
            forward_signals: list[JSONObject] | None = None
            selection_reports: list[FundamentalSelectionReport] = []
            if reports_artifact_id is not None:
                bundle = await self.load_financial_reports_bundle(reports_artifact_id)
                if bundle is not None:
                    loaded_reports, loaded_forward_signals = bundle
                    selection_reports = project_selection_reports(loaded_reports)
                    financial_reports = loaded_reports
                    forward_signals = loaded_forward_signals

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
                    forward_signals=forward_signals,
                )
            except Exception as exc:
                log_event(
                    logger,
                    event="fundamental_model_selection_artifact_failed",
                    message="fundamental model selection artifact generation failed",
                    level=logging.ERROR,
                    error_code="FUNDAMENTAL_MODEL_ARTIFACT_FAILED",
                    fields={"exception": str(exc), "ticker": resolved_ticker},
                )
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
            log_event(
                logger,
                event="fundamental_model_selection_failed",
                message="fundamental model selection failed",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_MODEL_SELECTION_FAILED",
                fields={"exception": str(exc)},
            )
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
            [str, str | None, list[JSONObject], list[JSONObject] | None],
            ParamBuildResult,
        ],
        get_skill_fn: Callable[[str], object | None],
    ) -> FundamentalNodeResult:
        log_event(
            logger,
            event="fundamental_valuation_started",
            message="fundamental valuation started",
        )
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

            bundle = await self.load_financial_reports_bundle(reports_artifact_id)
            if bundle is None:
                raise ValueError(
                    "Missing financial reports artifact data for valuation"
                )
            reports_raw, forward_signals = bundle
            if not reports_raw:
                raise ValueError("Empty financial reports data for valuation")

            build_result = build_params_fn(
                model_type,
                ticker,
                reports_raw,
                forward_signals,
            )

            if build_result.assumptions:
                log_event(
                    logger,
                    event="fundamental_valuation_assumptions_applied",
                    message="controlled valuation assumptions applied",
                    level=logging.WARNING,
                    error_code="FUNDAMENTAL_ASSUMPTIONS_APPLIED",
                    fields={
                        "model_type": model_type,
                        "assumption_count": len(build_result.assumptions),
                        "assumptions": build_result.assumptions,
                    },
                )
            if isinstance(build_result.metadata, Mapping):
                forward_signal_raw = build_result.metadata.get("forward_signal")
                if isinstance(forward_signal_raw, Mapping):
                    log_event(
                        logger,
                        event="fundamental_forward_signal_policy_applied",
                        message="forward signal policy summary recorded",
                        fields={
                            "model_type": model_type,
                            "signals_total": forward_signal_raw.get("signals_total"),
                            "signals_accepted": forward_signal_raw.get(
                                "signals_accepted"
                            ),
                            "signals_rejected": forward_signal_raw.get(
                                "signals_rejected"
                            ),
                            "growth_adjustment_bps": forward_signal_raw.get(
                                "growth_adjustment_bps"
                            ),
                            "margin_adjustment_bps": forward_signal_raw.get(
                                "margin_adjustment_bps"
                            ),
                            "forward_signal_risk_level": forward_signal_raw.get(
                                "risk_level"
                            ),
                            "source_types": forward_signal_raw.get("source_types"),
                        },
                    )

            if build_result.missing:
                log_event(
                    logger,
                    event="fundamental_valuation_missing_inputs",
                    message="fundamental valuation missing required inputs",
                    level=logging.ERROR,
                    error_code="FUNDAMENTAL_VALUATION_INPUTS_MISSING",
                    fields={
                        "ticker": ticker,
                        "model_type": model_type,
                        "missing_inputs": build_result.missing,
                        "assumptions": build_result.assumptions,
                    },
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
            calculation_error = result.get("error")
            if isinstance(calculation_error, str) and calculation_error:
                log_event(
                    logger,
                    event="fundamental_valuation_calculation_error",
                    message="valuation calculator returned error payload",
                    level=logging.ERROR,
                    error_code="FUNDAMENTAL_VALUATION_CALCULATION_ERROR",
                    fields={
                        "ticker": ticker,
                        "model_type": model_type,
                        "error": calculation_error,
                    },
                )
                return FundamentalNodeResult(
                    update=self.build_valuation_error_update(calculation_error),
                    goto="END",
                )

            mc_completion_fields = _build_monte_carlo_completion_fields(result)
            forward_signal_completion_fields = _build_forward_signal_completion_fields(
                forward_signals=forward_signals,
                build_metadata=(
                    build_result.metadata
                    if isinstance(build_result.metadata, Mapping)
                    else None
                ),
            )
            log_event(
                logger,
                event="fundamental_valuation_completed",
                message="fundamental valuation completed",
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    **mc_completion_fields,
                    **forward_signal_completion_fields,
                },
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
                    build_metadata=build_result.metadata,
                ),
                goto="END",
            )
        except Exception as exc:
            log_event(
                logger,
                event="fundamental_valuation_failed",
                message="fundamental valuation failed",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_VALUATION_FAILED",
                fields={"exception": str(exc)},
            )
            return FundamentalNodeResult(
                update=self.build_valuation_error_update(str(exc)),
                goto="END",
            )
