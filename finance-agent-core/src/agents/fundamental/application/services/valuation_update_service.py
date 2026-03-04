from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from src.agents.fundamental.application.context_mapper_service import (
    build_fundamental_app_context,
)
from src.agents.fundamental.application.dto import FundamentalAppContextDTO
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject

from .valuation_assumption_breakdown_service import build_assumption_breakdown
from .valuation_data_freshness_service import build_data_freshness
from .valuation_distribution_preview_service import (
    build_distribution_scenarios,
    coerce_float,
    extract_distribution_summary,
    resolve_preview_valuation_metrics,
)


def _build_mapper_context(
    intent_ctx: dict[str, object],
    resolved_ticker: str | None,
    *,
    status: str,
    model_type: str | None = None,
    valuation_summary: str | None = None,
    assumption_breakdown: JSONObject | None = None,
    data_freshness: JSONObject | None = None,
    assumption_risk_level: str | None = None,
    data_quality_flags: list[str] | None = None,
    time_alignment_status: str | None = None,
    forward_signal_summary: JSONObject | None = None,
    forward_signal_risk_level: str | None = None,
    forward_signal_evidence_count: int | None = None,
) -> FundamentalAppContextDTO:
    return build_fundamental_app_context(
        intent_ctx,
        resolved_ticker,
        status=status,
        model_type=model_type,
        valuation_summary=valuation_summary,
        assumption_breakdown=assumption_breakdown,
        data_freshness=data_freshness,
        assumption_risk_level=assumption_risk_level,
        data_quality_flags=data_quality_flags,
        time_alignment_status=time_alignment_status,
        forward_signal_summary=forward_signal_summary,
        forward_signal_risk_level=forward_signal_risk_level,
        forward_signal_evidence_count=forward_signal_evidence_count,
    )


class _BuildValuationArtifactFn(Protocol):
    def __call__(
        self,
        *,
        ticker: str | None,
        model_type: str,
        reports_artifact_id: str,
        preview: JSONObject,
    ) -> AgentOutputArtifactPayload: ...


def build_valuation_missing_inputs_update(
    *,
    fundamental: dict[str, object],
    missing_inputs: list[str],
    assumptions: list[str],
) -> JSONObject:
    fa_update = fundamental.copy()
    return {
        "fundamental_analysis": fa_update,
        "current_node": "calculation",
        "internal_progress": {"calculation": "error"},
        "node_statuses": {"fundamental_analysis": "error"},
        "error_logs": [
            {
                "node": "calculation",
                "error": f"Missing SEC XBRL inputs: {', '.join(missing_inputs)}",
                "severity": "error",
            }
        ],
    }


def build_valuation_success_update(
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
    summarize_preview: Callable[
        [FundamentalAppContextDTO, list[JSONObject]], JSONObject
    ],
    build_valuation_artifact_fn: _BuildValuationArtifactFn,
    build_metadata: JSONObject | None = None,
) -> JSONObject:
    fa_update = fundamental.copy()

    distribution_summary = extract_distribution_summary(calculation_metrics)
    shares_outstanding = coerce_float(params_dump.get("shares_outstanding"))
    (
        equity_value_raw,
        intrinsic_value_raw,
        upside_potential_raw,
    ) = resolve_preview_valuation_metrics(
        calculation_metrics=calculation_metrics,
        params_dump=params_dump,
        distribution_summary=distribution_summary,
    )
    distribution_scenarios = build_distribution_scenarios(
        distribution_summary,
        shares_outstanding=shares_outstanding,
    )
    assumption_breakdown = build_assumption_breakdown(
        assumptions=assumptions,
        params_dump=params_dump,
        calculation_metrics=calculation_metrics,
        build_metadata=build_metadata,
    )
    assumption_risk_level = assumption_breakdown.get("assumption_risk_level")
    data_quality_flags = assumption_breakdown.get("data_quality_flags")
    time_alignment_status = assumption_breakdown.get("time_alignment_status")
    forward_signal_summary = assumption_breakdown.get("forward_signal_summary")
    forward_signal_risk_level = assumption_breakdown.get("forward_signal_risk_level")
    forward_signal_evidence_count = assumption_breakdown.get(
        "forward_signal_evidence_count"
    )
    audit_summary = assumption_breakdown.get("audit_summary")
    parameter_source_summary = assumption_breakdown.get("parameter_source_summary")
    data_quality_flags_list = (
        [item for item in data_quality_flags if isinstance(item, str) and item]
        if isinstance(data_quality_flags, list)
        else None
    )
    data_freshness = build_data_freshness(
        reports_raw=reports_raw,
        build_metadata=build_metadata,
    )
    app_context = _build_mapper_context(
        intent_ctx,
        ticker,
        status="calculated",
        model_type=model_type,
        assumption_breakdown=assumption_breakdown,
        data_freshness=data_freshness,
        assumption_risk_level=(
            assumption_risk_level if isinstance(assumption_risk_level, str) else None
        ),
        data_quality_flags=data_quality_flags_list,
        time_alignment_status=(
            time_alignment_status if isinstance(time_alignment_status, str) else None
        ),
        forward_signal_summary=(
            forward_signal_summary
            if isinstance(forward_signal_summary, Mapping)
            else None
        ),
        forward_signal_risk_level=(
            forward_signal_risk_level
            if isinstance(forward_signal_risk_level, str)
            else None
        ),
        forward_signal_evidence_count=(
            int(forward_signal_evidence_count)
            if isinstance(forward_signal_evidence_count, int | float)
            else None
        ),
    )
    preview = summarize_preview(app_context, reports_raw)
    preview.update(
        {
            "model_type": model_type,
            "equity_value": equity_value_raw,
            "intrinsic_value": intrinsic_value_raw,
            "upside_potential": upside_potential_raw,
            "status": "calculated",
        }
    )
    if distribution_summary is not None:
        preview["distribution_summary"] = distribution_summary
    if distribution_scenarios is not None:
        preview["distribution_scenarios"] = distribution_scenarios
    if isinstance(assumption_risk_level, str) and assumption_risk_level:
        preview["assumption_risk_level"] = assumption_risk_level
    if data_quality_flags_list is not None:
        preview["data_quality_flags"] = data_quality_flags_list
    if isinstance(time_alignment_status, str) and time_alignment_status:
        preview["time_alignment_status"] = time_alignment_status
    if isinstance(forward_signal_summary, Mapping):
        preview["forward_signal_summary"] = dict(forward_signal_summary)
    if isinstance(forward_signal_risk_level, str) and forward_signal_risk_level:
        preview["forward_signal_risk_level"] = forward_signal_risk_level
    if isinstance(forward_signal_evidence_count, int | float):
        preview["forward_signal_evidence_count"] = int(forward_signal_evidence_count)
    if isinstance(audit_summary, Mapping):
        preview["audit_summary"] = dict(audit_summary)
    if isinstance(parameter_source_summary, Mapping):
        preview["parameter_source_summary"] = dict(parameter_source_summary)
    artifact = build_valuation_artifact_fn(
        ticker=ticker,
        model_type=model_type,
        reports_artifact_id=reports_artifact_id,
        preview=preview,
    )
    fa_update["artifact"] = artifact
    return {
        "fundamental_analysis": fa_update,
        "current_node": "calculation",
        "internal_progress": {"calculation": "done"},
        "node_statuses": {"fundamental_analysis": "done"},
        "artifact": artifact,
    }


def build_valuation_error_update(error: str) -> JSONObject:
    return {
        "error_logs": [
            {
                "node": "calculation",
                "error": error,
                "severity": "error",
            }
        ],
        "internal_progress": {"calculation": "error"},
        "node_statuses": {"fundamental_analysis": "error"},
    }
