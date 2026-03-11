from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from src.agents.fundamental.application.workflow_orchestrator.context_mapper_service import (
    build_fundamental_app_context,
)
from src.agents.fundamental.application.workflow_orchestrator.dto import (
    FundamentalAppContextDTO,
)
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


def _coerce_numeric_series(raw: object) -> list[float] | None:
    if not isinstance(raw, list):
        return None
    output: list[float] = []
    for item in raw:
        value = coerce_float(item)
        if value is None:
            return None
        output.append(value)
    if not output:
        return None
    return output


def _extract_valuation_diagnostics(
    *,
    params_dump: Mapping[str, object],
    calculation_metrics: Mapping[str, object],
    assumptions: list[str],
    forward_signal_summary: Mapping[str, object] | None = None,
) -> JSONObject | None:
    details_raw = calculation_metrics.get("details")
    details = details_raw if isinstance(details_raw, Mapping) else {}

    growth_rates_converged = _coerce_numeric_series(
        details.get("growth_rates_converged")
    )
    terminal_growth_effective = coerce_float(details.get("terminal_growth_effective"))
    if terminal_growth_effective is None:
        terminal_growth_effective = coerce_float(params_dump.get("terminal_growth"))
    sensitivity_summary = _extract_sensitivity_summary(details)

    diagnostics: JSONObject = {}
    model_variant_raw = params_dump.get("model_variant")
    model_variant = model_variant_raw if isinstance(model_variant_raw, str) else None
    if model_variant in {"dcf_growth", "dcf_standard"}:
        diagnostics["base_guardrail_profile"] = model_variant
        diagnostics["base_growth_guardrail_applied"] = False
        diagnostics["base_margin_guardrail_applied"] = False
    if growth_rates_converged is not None:
        diagnostics["growth_rates_converged"] = growth_rates_converged
    if terminal_growth_effective is not None:
        diagnostics["terminal_growth_effective"] = terminal_growth_effective
    if sensitivity_summary is not None:
        diagnostics["sensitivity_summary"] = sensitivity_summary
    for statement in assumptions:
        if statement.startswith(
            "consensus_growth_rate decayed into near-term DCF growth path"
        ):
            diagnostics["growth_consensus_policy"] = "decayed"
            horizon = _extract_horizon_token(statement)
            if horizon is not None:
                diagnostics["growth_consensus_horizon"] = horizon
            window_years = _extract_int_key_token(statement, key="window_years")
            if window_years is not None:
                diagnostics["growth_consensus_window_years"] = window_years
        if statement.startswith(
            "consensus_growth_rate ignored for long-horizon DCF growth blend"
        ):
            diagnostics["growth_consensus_policy"] = "ignored"
            horizon = _extract_horizon_token(statement)
            if horizon is not None:
                diagnostics["growth_consensus_horizon"] = horizon
        elif statement.startswith(
            "consensus_growth_rate included in long-horizon DCF growth blend"
        ):
            diagnostics["growth_consensus_policy"] = "included"
            horizon = _extract_horizon_token(statement)
            if horizon is not None:
                diagnostics["growth_consensus_horizon"] = horizon
        elif (
            statement.startswith(
                "consensus_growth_rate horizon metadata missing; treated as long-horizon for compatibility"
            )
            or statement.startswith(
                "consensus_growth_rate market datum missing; treated as long-horizon for compatibility"
            )
            or statement.startswith(
                "consensus_growth_rate horizon unknown; treated as long-horizon for compatibility"
            )
        ):
            diagnostics["growth_consensus_policy"] = "compatibility_assumed"
            diagnostics["growth_consensus_horizon"] = "unknown"
        if statement.startswith(
            "terminal_growth market anchor stale; fallback to policy default"
        ):
            diagnostics["terminal_anchor_policy"] = "policy_default_market_stale"
            diagnostics["terminal_anchor_stale_fallback"] = True
        elif statement.startswith("base_growth_guardrail applied"):
            diagnostics["base_growth_guardrail_applied"] = True
            _apply_base_guardrail_diagnostics(
                diagnostics=diagnostics,
                statement=statement,
                prefix="base_growth",
            )
        elif statement.startswith("base_margin_guardrail applied"):
            diagnostics["base_margin_guardrail_applied"] = True
            _apply_base_guardrail_diagnostics(
                diagnostics=diagnostics,
                statement=statement,
                prefix="base_margin",
            )
    growth_applied = diagnostics.get("base_growth_guardrail_applied")
    margin_applied = diagnostics.get("base_margin_guardrail_applied")
    if isinstance(growth_applied, bool) and isinstance(margin_applied, bool):
        diagnostics["base_guardrail_hit_count"] = int(growth_applied) + int(
            margin_applied
        )

    if isinstance(forward_signal_summary, Mapping):
        mapping_version = forward_signal_summary.get("mapping_version")
        if isinstance(mapping_version, str) and mapping_version:
            diagnostics["forward_signal_mapping_version"] = mapping_version

        calibration_applied = forward_signal_summary.get("calibration_applied")
        if isinstance(calibration_applied, bool):
            diagnostics["forward_signal_calibration_applied"] = calibration_applied

    if not diagnostics:
        return None
    return diagnostics


def _extract_horizon_token(statement: str) -> str | None:
    marker = "horizon="
    start = statement.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end_candidates = [statement.find(",", start), statement.find(")", start)]
    ends = [value for value in end_candidates if value >= 0]
    end = min(ends) if ends else len(statement)
    token = statement[start:end]
    normalized = token.strip().lower()
    return normalized or None


def _apply_base_guardrail_diagnostics(
    *,
    diagnostics: JSONObject,
    statement: str,
    prefix: str,
) -> None:
    version = _extract_key_token(statement, key="version")
    profile = _extract_key_token(statement, key="profile")
    raw_year1 = _extract_float_key_token(statement, key="raw_year1")
    raw_year_n = _extract_float_key_token(statement, key="raw_yearN")
    guarded_year1 = _extract_float_key_token(statement, key="guarded_year1")
    guarded_year_n = _extract_float_key_token(statement, key="guarded_yearN")
    reasons_raw = _extract_key_token(statement, key="reasons")

    if version is not None:
        diagnostics[f"{prefix}_guardrail_version"] = version
    if profile is not None:
        diagnostics[f"{prefix}_guardrail_profile"] = profile
    if raw_year1 is not None:
        diagnostics[f"{prefix}_raw_year1"] = raw_year1
    if raw_year_n is not None:
        diagnostics[f"{prefix}_raw_yearN"] = raw_year_n
    if guarded_year1 is not None:
        diagnostics[f"{prefix}_guarded_year1"] = guarded_year1
    if guarded_year_n is not None:
        diagnostics[f"{prefix}_guarded_yearN"] = guarded_year_n
    if reasons_raw is not None:
        reasons = [item for item in reasons_raw.split("|") if item]
        diagnostics[f"{prefix}_guardrail_reasons"] = reasons
        diagnostics[f"{prefix}_guardrail_reason_count"] = len(reasons)


def _extract_float_key_token(statement: str, *, key: str) -> float | None:
    token = _extract_key_token(statement, key=key)
    if token is None:
        return None
    try:
        return float(token)
    except ValueError:
        return None


def _extract_int_key_token(statement: str, *, key: str) -> int | None:
    token = _extract_key_token(statement, key=key)
    if token is None:
        return None
    try:
        return int(float(token))
    except ValueError:
        return None


def _extract_key_token(statement: str, *, key: str) -> str | None:
    marker = f"{key}="
    start = statement.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end_candidates = [statement.find(",", start), statement.find(")", start)]
    ends = [candidate for candidate in end_candidates if candidate >= 0]
    end = min(ends) if ends else len(statement)
    token = statement[start:end].strip()
    return token or None


def _extract_sensitivity_summary(
    details: Mapping[str, object],
) -> JSONObject | None:
    raw = details.get("sensitivity_summary")
    if not isinstance(raw, Mapping):
        return None

    output: JSONObject = {}
    enabled_raw = raw.get("enabled")
    if isinstance(enabled_raw, bool):
        output["enabled"] = enabled_raw

    scenario_count_raw = raw.get("scenario_count")
    if isinstance(scenario_count_raw, int):
        output["scenario_count"] = scenario_count_raw
    elif isinstance(scenario_count_raw, float):
        output["scenario_count"] = int(scenario_count_raw)

    max_upside_raw = coerce_float(raw.get("max_upside_delta_pct"))
    if max_upside_raw is not None:
        output["max_upside_delta_pct"] = max_upside_raw

    max_downside_raw = coerce_float(raw.get("max_downside_delta_pct"))
    if max_downside_raw is not None:
        output["max_downside_delta_pct"] = max_downside_raw

    top_drivers_raw = raw.get("top_drivers")
    if isinstance(top_drivers_raw, list):
        top_drivers: list[JSONObject] = []
        for item in top_drivers_raw:
            if not isinstance(item, Mapping):
                continue
            payload: JSONObject = {}
            dimension_raw = item.get("shock_dimension")
            if isinstance(dimension_raw, str) and dimension_raw:
                payload["shock_dimension"] = dimension_raw
            shock_value_raw = item.get("shock_value_bp")
            if isinstance(shock_value_raw, int):
                payload["shock_value_bp"] = shock_value_raw
            elif isinstance(shock_value_raw, float):
                payload["shock_value_bp"] = int(shock_value_raw)
            delta_raw = coerce_float(item.get("delta_pct_vs_base"))
            if delta_raw is not None:
                payload["delta_pct_vs_base"] = delta_raw
            if payload:
                top_drivers.append(payload)
        if top_drivers:
            output["top_drivers"] = top_drivers

    if not output:
        return None
    return output


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
    valuation_diagnostics = _extract_valuation_diagnostics(
        params_dump=params_dump,
        calculation_metrics=calculation_metrics,
        assumptions=assumptions,
        forward_signal_summary=(
            forward_signal_summary
            if isinstance(forward_signal_summary, Mapping)
            else None
        ),
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
    if valuation_diagnostics is not None:
        preview["valuation_diagnostics"] = valuation_diagnostics
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
