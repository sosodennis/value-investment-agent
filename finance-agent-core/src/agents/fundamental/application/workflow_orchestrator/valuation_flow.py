from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import Protocol

from src.agents.fundamental.application.workflow_orchestrator.services.valuation_completion_fields_service import (
    build_forward_signal_completion_fields,
    build_monte_carlo_completion_fields,
)
from src.agents.fundamental.application.workflow_orchestrator.services.valuation_distribution_preview_service import (
    coerce_float,
    extract_distribution_summary,
)
from src.agents.fundamental.application.workflow_orchestrator.services.valuation_execution_context_service import (
    resolve_valuation_execution_context,
)
from src.agents.fundamental.application.workflow_orchestrator.services.valuation_execution_result_service import (
    execute_valuation_calculation,
)
from src.agents.fundamental.application.workflow_orchestrator.services.valuation_replay_contracts import (
    INTERNAL_REPLAY_MARKET_SNAPSHOT_KEY,
    VALUATION_REPLAY_SCHEMA_VERSION,
)
from src.agents.fundamental.subdomains.core_valuation.domain.parameterization import (
    apply_missing_metric_policy,
)
from src.agents.fundamental.subdomains.core_valuation.domain.parameterization.contracts import (
    ParamBuildResult,
)
from src.agents.fundamental.subdomains.forward_signals.interface.contracts import (
    ForwardSignalPayload,
)
from src.agents.fundamental.subdomains.forward_signals.interface.serializers import (
    serialize_forward_signals,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
FundamentalNodeResult = WorkflowNodeResult
_VALUATION_COMPUTE_CONCURRENCY_LIMIT = 2
_valuation_compute_semaphore: asyncio.Semaphore | None = None
_XBRL_QUALITY_BLOCKED_CODE = "FUNDAMENTAL_XBRL_QUALITY_BLOCKED"
_WARN_ONLY_MISSING_INPUT_FIELDS = (
    "tax_rate",
    "da_rates",
    "capex_rates",
    "wc_rates",
    "sbc_rates",
)


class ValuationRuntime(Protocol):
    async def save_financial_reports(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_financial_reports_bundle(
        self, artifact_id: str
    ) -> tuple[list[JSONObject], list[JSONObject] | None] | None: ...

    def build_valuation_missing_inputs_update(
        self,
        *,
        fundamental: dict[str, object],
        missing_inputs: list[str],
        assumptions: list[str],
    ) -> JSONObject: ...

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
    ) -> JSONObject: ...

    def build_valuation_error_update(self, error: str) -> JSONObject: ...


def _get_valuation_compute_semaphore() -> asyncio.Semaphore:
    global _valuation_compute_semaphore
    if _valuation_compute_semaphore is None:
        _valuation_compute_semaphore = asyncio.Semaphore(
            _VALUATION_COMPUTE_CONCURRENCY_LIMIT
        )
    return _valuation_compute_semaphore


async def _offload_valuation_compute(
    func: Callable[..., object],
    /,
    *args: object,
    **kwargs: object,
) -> object:
    async with _get_valuation_compute_semaphore():
        return await asyncio.to_thread(func, *args, **kwargs)


def _extract_numeric_metric(
    calculation_metrics: Mapping[str, object], key: str
) -> float | None:
    direct = coerce_float(calculation_metrics.get(key))
    if direct is not None:
        return direct
    details_raw = calculation_metrics.get("details")
    if isinstance(details_raw, Mapping):
        return coerce_float(details_raw.get(key))
    return None


def _extract_numeric_series_metric(
    calculation_metrics: Mapping[str, object],
    key: str,
) -> list[float] | None:
    direct = _coerce_numeric_series(calculation_metrics.get(key))
    if direct is not None:
        return direct
    details_raw = calculation_metrics.get("details")
    if isinstance(details_raw, Mapping):
        return _coerce_numeric_series(details_raw.get(key))
    return None


def _extract_sensitivity_summary(
    calculation_metrics: Mapping[str, object],
) -> Mapping[str, object] | None:
    details_raw = calculation_metrics.get("details")
    if not isinstance(details_raw, Mapping):
        return None
    sensitivity_raw = details_raw.get("sensitivity_summary")
    if not isinstance(sensitivity_raw, Mapping):
        return None
    return sensitivity_raw


def _extract_distribution_value_per_share(
    *,
    distribution_summary: Mapping[str, object] | None,
    key: str,
    shares_outstanding: float | None,
) -> float | None:
    if distribution_summary is None:
        return None
    summary_raw = distribution_summary.get("summary")
    if not isinstance(summary_raw, Mapping):
        return None
    value = coerce_float(summary_raw.get(key))
    if value is None:
        return None
    metric_type_raw = distribution_summary.get("metric_type")
    metric_type = metric_type_raw if isinstance(metric_type_raw, str) else None
    if metric_type in {"equity_value_total", "equity_value"}:
        if shares_outstanding is None or shares_outstanding <= 0:
            return None
        return value / shares_outstanding
    return value


def _extract_distribution_diagnostic_per_share(
    *,
    distribution_summary: Mapping[str, object] | None,
    key: str,
    shares_outstanding: float | None,
) -> float | None:
    if distribution_summary is None:
        return None
    diagnostics_raw = distribution_summary.get("diagnostics")
    if not isinstance(diagnostics_raw, Mapping):
        return None
    value = coerce_float(diagnostics_raw.get(key))
    if value is None:
        return None
    metric_type_raw = distribution_summary.get("metric_type")
    metric_type = metric_type_raw if isinstance(metric_type_raw, str) else None
    if metric_type in {"equity_value_total", "equity_value"}:
        if shares_outstanding is None or shares_outstanding <= 0:
            return None
        return value / shares_outstanding
    return value


def _coerce_numeric_series(raw: object) -> list[float] | None:
    if not isinstance(raw, list | tuple):
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


def _append_series_snapshot_fields(
    *,
    fields: JSONObject,
    series: list[float] | None,
    prefix: str,
) -> None:
    if not series:
        return
    fields[f"{prefix}_count"] = len(series)
    fields[f"{prefix}_year1"] = series[0]
    fields[f"{prefix}_yearN"] = series[-1]
    fields[f"{prefix}_min"] = min(series)
    fields[f"{prefix}_max"] = max(series)


def _build_valuation_metrics_snapshot_fields(
    *,
    params_dump: Mapping[str, object],
    calculation_metrics: Mapping[str, object],
    assumptions: list[str] | None = None,
) -> JSONObject:
    fields: JSONObject = {}
    model_variant_raw = params_dump.get("model_variant")
    model_variant = model_variant_raw if isinstance(model_variant_raw, str) else None
    if model_variant in {"dcf_growth", "dcf_standard"}:
        fields["base_guardrail_profile"] = model_variant
        fields["base_growth_guardrail_applied"] = False
        fields["base_margin_guardrail_applied"] = False
        fields["base_capex_guardrail_applied"] = False
        fields["base_wc_guardrail_applied"] = False

    point_intrinsic = _extract_numeric_metric(calculation_metrics, "intrinsic_value")
    point_equity = _extract_numeric_metric(calculation_metrics, "equity_value")
    point_upside = _extract_numeric_metric(calculation_metrics, "upside_potential")
    current_price = coerce_float(params_dump.get("current_price"))
    shares_outstanding = coerce_float(params_dump.get("shares_outstanding"))
    distribution_summary = extract_distribution_summary(dict(calculation_metrics))

    if point_intrinsic is not None:
        fields["point_intrinsic_value"] = point_intrinsic
    if point_equity is not None:
        fields["point_equity_value"] = point_equity
    if point_upside is not None:
        fields["point_upside_potential"] = point_upside
    if current_price is not None:
        fields["current_price"] = current_price
    if shares_outstanding is not None:
        fields["shares_outstanding"] = shares_outstanding

    distribution_metric_type: str | None = None
    if isinstance(distribution_summary, Mapping):
        metric_type_raw = distribution_summary.get("metric_type")
        if isinstance(metric_type_raw, str) and metric_type_raw:
            distribution_metric_type = metric_type_raw
            fields["distribution_metric_type"] = metric_type_raw

    p5 = _extract_distribution_value_per_share(
        distribution_summary=distribution_summary,
        key="percentile_5",
        shares_outstanding=shares_outstanding,
    )
    p50 = _extract_distribution_value_per_share(
        distribution_summary=distribution_summary,
        key="median",
        shares_outstanding=shares_outstanding,
    )
    p95 = _extract_distribution_value_per_share(
        distribution_summary=distribution_summary,
        key="percentile_95",
        shares_outstanding=shares_outstanding,
    )
    if p5 is not None:
        fields["distribution_p5_per_share"] = p5
    if p50 is not None:
        fields["distribution_p50_per_share"] = p50
    if p95 is not None:
        fields["distribution_p95_per_share"] = p95

    base_case = _extract_distribution_diagnostic_per_share(
        distribution_summary=distribution_summary,
        key="base_case_intrinsic_value",
        shares_outstanding=shares_outstanding,
    )
    if base_case is not None:
        fields["distribution_base_case_per_share"] = base_case

    if (
        point_upside is None
        and point_intrinsic is not None
        and current_price is not None
        and current_price > 0
    ):
        point_upside = (point_intrinsic - current_price) / current_price
        fields["point_upside_potential"] = point_upside

    if point_intrinsic is not None and current_price is not None and current_price > 0:
        fields["point_vs_current_pct"] = (
            point_intrinsic - current_price
        ) / current_price

    if current_price is not None and p95 is not None and p95 > 0:
        fields["current_vs_p95_pct"] = (current_price - p95) / p95
    if current_price is not None and p5 is not None and p5 > 0:
        fields["current_vs_p5_pct"] = (current_price - p5) / p5
    if point_intrinsic is not None and p50 is not None and p50 > 0:
        fields["point_vs_p50_pct"] = (point_intrinsic - p50) / p50
    if point_intrinsic is not None and base_case is not None and base_case > 0:
        fields["point_vs_distribution_base_case_pct"] = (
            point_intrinsic - base_case
        ) / base_case

    # Helps quickly reason about possible denominator mismatch around share class choices.
    if point_equity is not None and point_intrinsic is not None and point_intrinsic > 0:
        fields["implied_shares_from_point"] = point_equity / point_intrinsic

    effective_wacc = coerce_float(params_dump.get("wacc"))
    effective_terminal_growth = coerce_float(params_dump.get("terminal_growth"))
    terminal_growth_effective = _extract_numeric_metric(
        calculation_metrics, "terminal_growth_effective"
    )
    effective_risk_free_rate = coerce_float(params_dump.get("risk_free_rate"))
    effective_beta = coerce_float(params_dump.get("beta"))
    effective_market_risk_premium = coerce_float(params_dump.get("market_risk_premium"))
    if effective_wacc is not None:
        fields["effective_wacc"] = effective_wacc
    if effective_terminal_growth is not None:
        fields["effective_terminal_growth"] = effective_terminal_growth
    if terminal_growth_effective is not None:
        fields["terminal_growth_effective"] = terminal_growth_effective
    if effective_risk_free_rate is not None:
        fields["effective_risk_free_rate"] = effective_risk_free_rate
    if effective_beta is not None:
        fields["effective_beta"] = effective_beta
    if effective_market_risk_premium is not None:
        fields["effective_market_risk_premium"] = effective_market_risk_premium
    if effective_wacc is not None and effective_terminal_growth is not None:
        fields["effective_wacc_minus_terminal_growth"] = (
            effective_wacc - effective_terminal_growth
        )

    _append_series_snapshot_fields(
        fields=fields,
        series=_coerce_numeric_series(params_dump.get("growth_rates")),
        prefix="effective_growth_rate",
    )
    growth_rates_converged = _extract_numeric_series_metric(
        calculation_metrics, "growth_rates_converged"
    )
    if growth_rates_converged:
        fields["growth_rates_converged"] = growth_rates_converged
    _append_series_snapshot_fields(
        fields=fields,
        series=growth_rates_converged,
        prefix="growth_rates_converged",
    )
    _append_series_snapshot_fields(
        fields=fields,
        series=_coerce_numeric_series(params_dump.get("operating_margins")),
        prefix="effective_operating_margin",
    )

    # Preserve metric type even when summary is missing so downstream triage is simpler.
    if distribution_metric_type is None and isinstance(distribution_summary, Mapping):
        fields["distribution_metric_type"] = "unknown"

    sensitivity_summary = _extract_sensitivity_summary(calculation_metrics)
    if isinstance(sensitivity_summary, Mapping):
        sensitivity_enabled = sensitivity_summary.get("enabled")
        if isinstance(sensitivity_enabled, bool):
            fields["sensitivity_enabled"] = sensitivity_enabled

        scenario_count_raw = sensitivity_summary.get("scenario_count")
        if isinstance(scenario_count_raw, int):
            fields["sensitivity_scenario_count"] = scenario_count_raw
        elif isinstance(scenario_count_raw, float):
            fields["sensitivity_scenario_count"] = int(scenario_count_raw)

        max_upside_raw = coerce_float(sensitivity_summary.get("max_upside_delta_pct"))
        if max_upside_raw is not None:
            fields["sensitivity_max_upside_delta_pct"] = max_upside_raw

        max_downside_raw = coerce_float(
            sensitivity_summary.get("max_downside_delta_pct")
        )
        if max_downside_raw is not None:
            fields["sensitivity_max_downside_delta_pct"] = max_downside_raw

        top_drivers_raw = sensitivity_summary.get("top_drivers")
        if isinstance(top_drivers_raw, list) and top_drivers_raw:
            first = top_drivers_raw[0]
            if isinstance(first, Mapping):
                top_dimension = first.get("shock_dimension")
                top_shock = first.get("shock_value_bp")
                top_delta = coerce_float(first.get("delta_pct_vs_base"))
                if isinstance(top_dimension, str) and top_dimension:
                    fields["sensitivity_top_driver_dimension"] = top_dimension
                if isinstance(top_shock, int):
                    fields["sensitivity_top_driver_shock_bp"] = top_shock
                elif isinstance(top_shock, float):
                    fields["sensitivity_top_driver_shock_bp"] = int(top_shock)
                if top_delta is not None:
                    fields["sensitivity_top_driver_delta_pct"] = top_delta

    if assumptions:
        for statement in assumptions:
            if statement.startswith(
                "consensus_growth_rate decayed into near-term DCF growth path"
            ):
                fields["growth_consensus_policy"] = "decayed"
                horizon = _extract_horizon_token(statement)
                if horizon is not None:
                    fields["growth_consensus_horizon"] = horizon
                window_years = _extract_int_key_token(statement, key="window_years")
                if window_years is not None:
                    fields["growth_consensus_window_years"] = window_years
            if statement.startswith(
                "consensus_growth_rate ignored for long-horizon DCF growth blend"
            ):
                fields["growth_consensus_policy"] = "ignored"
                horizon = _extract_horizon_token(statement)
                if horizon is not None:
                    fields["growth_consensus_horizon"] = horizon
            elif statement.startswith(
                "consensus_growth_rate included in long-horizon DCF growth blend"
            ):
                fields["growth_consensus_policy"] = "included"
                horizon = _extract_horizon_token(statement)
                if horizon is not None:
                    fields["growth_consensus_horizon"] = horizon
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
                fields["growth_consensus_policy"] = "compatibility_assumed"
                fields["growth_consensus_horizon"] = "unknown"

            if statement.startswith(
                "terminal_growth market anchor stale; fallback to policy default"
            ):
                fields["terminal_anchor_policy"] = "policy_default_market_stale"
                fields["terminal_anchor_stale_fallback"] = True
            elif statement.startswith("base_growth_guardrail applied"):
                fields["base_growth_guardrail_applied"] = True
                version = _extract_key_token(statement, key="version")
                profile = _extract_key_token(statement, key="profile")
                if version is not None:
                    fields["base_growth_guardrail_version"] = version
                if profile is not None:
                    fields["base_growth_guardrail_profile"] = profile
                raw_year1 = _extract_float_key_token(statement, key="raw_year1")
                raw_yearn = _extract_float_key_token(statement, key="raw_yearN")
                guarded_year1 = _extract_float_key_token(statement, key="guarded_year1")
                guarded_yearn = _extract_float_key_token(statement, key="guarded_yearN")
                reasons_raw = _extract_key_token(statement, key="reasons")
                if raw_year1 is not None:
                    fields["base_growth_raw_year1"] = raw_year1
                if raw_yearn is not None:
                    fields["base_growth_raw_yearN"] = raw_yearn
                if guarded_year1 is not None:
                    fields["base_growth_guarded_year1"] = guarded_year1
                if guarded_yearn is not None:
                    fields["base_growth_guarded_yearN"] = guarded_yearn
                if reasons_raw is not None:
                    reasons = [item for item in reasons_raw.split("|") if item]
                    fields["base_growth_guardrail_reasons"] = reasons
                    fields["base_growth_guardrail_reason_count"] = len(reasons)
            elif statement.startswith("base_margin_guardrail applied"):
                fields["base_margin_guardrail_applied"] = True
                version = _extract_key_token(statement, key="version")
                profile = _extract_key_token(statement, key="profile")
                if version is not None:
                    fields["base_margin_guardrail_version"] = version
                if profile is not None:
                    fields["base_margin_guardrail_profile"] = profile
                raw_year1 = _extract_float_key_token(statement, key="raw_year1")
                raw_yearn = _extract_float_key_token(statement, key="raw_yearN")
                guarded_year1 = _extract_float_key_token(statement, key="guarded_year1")
                guarded_yearn = _extract_float_key_token(statement, key="guarded_yearN")
                reasons_raw = _extract_key_token(statement, key="reasons")
                if raw_year1 is not None:
                    fields["base_margin_raw_year1"] = raw_year1
                if raw_yearn is not None:
                    fields["base_margin_raw_yearN"] = raw_yearn
                if guarded_year1 is not None:
                    fields["base_margin_guarded_year1"] = guarded_year1
                if guarded_yearn is not None:
                    fields["base_margin_guarded_yearN"] = guarded_yearn
                if reasons_raw is not None:
                    reasons = [item for item in reasons_raw.split("|") if item]
                    fields["base_margin_guardrail_reasons"] = reasons
                    fields["base_margin_guardrail_reason_count"] = len(reasons)
            elif statement.startswith("base_reinvestment_guardrail applied"):
                metric = _extract_key_token(statement, key="metric")
                if metric == "capex_rates":
                    metric_prefix = "base_capex"
                elif metric == "wc_rates":
                    metric_prefix = "base_wc"
                else:
                    metric_prefix = None
                if metric_prefix is None:
                    continue
                fields[f"{metric_prefix}_guardrail_applied"] = True
                version = _extract_key_token(statement, key="version")
                profile = _extract_key_token(statement, key="profile")
                if version is not None:
                    fields[f"{metric_prefix}_guardrail_version"] = version
                if profile is not None:
                    fields[f"{metric_prefix}_guardrail_profile"] = profile
                raw_year1 = _extract_float_key_token(statement, key="raw_year1")
                raw_yearn = _extract_float_key_token(statement, key="raw_yearN")
                guarded_year1 = _extract_float_key_token(statement, key="guarded_year1")
                guarded_yearn = _extract_float_key_token(statement, key="guarded_yearN")
                anchor = _extract_float_key_token(statement, key="anchor")
                anchor_samples = _extract_int_key_token(statement, key="anchor_samples")
                reasons_raw = _extract_key_token(statement, key="reasons")
                if raw_year1 is not None:
                    fields[f"{metric_prefix}_raw_year1"] = raw_year1
                if raw_yearn is not None:
                    fields[f"{metric_prefix}_raw_yearN"] = raw_yearn
                if guarded_year1 is not None:
                    fields[f"{metric_prefix}_guarded_year1"] = guarded_year1
                if guarded_yearn is not None:
                    fields[f"{metric_prefix}_guarded_yearN"] = guarded_yearn
                if anchor is not None:
                    fields[f"{metric_prefix}_guardrail_anchor"] = anchor
                if anchor_samples is not None:
                    fields[f"{metric_prefix}_guardrail_anchor_samples"] = anchor_samples
                if reasons_raw is not None:
                    reasons = [item for item in reasons_raw.split("|") if item]
                    fields[f"{metric_prefix}_guardrail_reasons"] = reasons
                    fields[f"{metric_prefix}_guardrail_reason_count"] = len(reasons)
    guardrail_hit_count = 0
    guardrail_field_seen = False
    for key in (
        "base_growth_guardrail_applied",
        "base_margin_guardrail_applied",
        "base_capex_guardrail_applied",
        "base_wc_guardrail_applied",
    ):
        value = fields.get(key)
        if isinstance(value, bool):
            guardrail_field_seen = True
            guardrail_hit_count += int(value)
    if guardrail_field_seen:
        fields["base_guardrail_hit_count"] = guardrail_hit_count
    return fields


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
    ends = [value for value in end_candidates if value >= 0]
    end = min(ends) if ends else len(statement)
    token = statement[start:end].strip()
    return token or None


def _detect_valuation_metric_mismatch(
    snapshot_fields: Mapping[str, object],
) -> str | None:
    point_upside = coerce_float(snapshot_fields.get("point_upside_potential"))
    current_vs_p95 = coerce_float(snapshot_fields.get("current_vs_p95_pct"))
    current_vs_p5 = coerce_float(snapshot_fields.get("current_vs_p5_pct"))
    point_vs_p50 = coerce_float(snapshot_fields.get("point_vs_p50_pct"))
    point_vs_mc_base = coerce_float(
        snapshot_fields.get("point_vs_distribution_base_case_pct")
    )

    if (
        point_upside is not None
        and current_vs_p95 is not None
        and point_upside > 0
        and current_vs_p95 > 0
    ):
        return "point_upside_positive_but_current_above_p95"
    if (
        point_upside is not None
        and current_vs_p5 is not None
        and point_upside < 0
        and current_vs_p5 < 0
    ):
        return "point_upside_negative_but_current_below_p5"
    if point_vs_p50 is not None and abs(point_vs_p50) >= 0.5:
        return "point_intrinsic_far_from_distribution_median"
    if point_vs_mc_base is not None and abs(point_vs_mc_base) >= 0.05:
        return "point_intrinsic_far_from_monte_carlo_base_case"
    return None


def _log_build_result_policy_events(
    *,
    model_type: str,
    build_result: ParamBuildResult,
) -> None:
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
        calibration_meta_raw = build_result.metadata.get("forward_signal_calibration")
        if isinstance(forward_signal_raw, Mapping):
            mapping_source = None
            mapping_path = None
            mapping_degraded_reason = None
            if isinstance(calibration_meta_raw, Mapping):
                source_raw = calibration_meta_raw.get("mapping_source")
                path_raw = calibration_meta_raw.get("mapping_path")
                degraded_raw = calibration_meta_raw.get("degraded_reason")
                if isinstance(source_raw, str) and source_raw:
                    mapping_source = source_raw
                if isinstance(path_raw, str) and path_raw:
                    mapping_path = path_raw
                if isinstance(degraded_raw, str) and degraded_raw:
                    mapping_degraded_reason = degraded_raw
            log_event(
                logger,
                event="fundamental_forward_signal_policy_applied",
                message="forward signal policy summary recorded",
                fields={
                    "model_type": model_type,
                    "signals_total": forward_signal_raw.get("signals_total"),
                    "signals_accepted": forward_signal_raw.get("signals_accepted"),
                    "signals_rejected": forward_signal_raw.get("signals_rejected"),
                    "raw_growth_adjustment_basis_points": forward_signal_raw.get(
                        "raw_growth_adjustment_basis_points"
                    ),
                    "raw_margin_adjustment_basis_points": forward_signal_raw.get(
                        "raw_margin_adjustment_basis_points"
                    ),
                    "growth_adjustment_basis_points": forward_signal_raw.get(
                        "growth_adjustment_basis_points"
                    ),
                    "margin_adjustment_basis_points": forward_signal_raw.get(
                        "margin_adjustment_basis_points"
                    ),
                    "calibration_applied": forward_signal_raw.get(
                        "calibration_applied"
                    ),
                    "mapping_version": forward_signal_raw.get("mapping_version"),
                    "mapping_source": mapping_source,
                    "mapping_path": mapping_path,
                    "mapping_degraded_reason": mapping_degraded_reason,
                    "forward_signal_risk_level": forward_signal_raw.get("risk_level"),
                    "source_types": forward_signal_raw.get("source_types"),
                },
            )


def _build_metadata_with_audit(
    *,
    base_metadata: Mapping[str, object] | None,
    audit_passed: bool | None,
    audit_messages: list[str],
) -> JSONObject:
    metadata: JSONObject = {}
    if isinstance(base_metadata, Mapping):
        metadata.update(dict(base_metadata))

    if audit_passed is None:
        return metadata

    warn_count = len([item for item in audit_messages if item.startswith("WARN:")])
    fail_count = len([item for item in audit_messages if item.startswith("FAIL:")])
    audit_payload: JSONObject = {
        "passed": audit_passed,
        "message_count": len(audit_messages),
        "warn_count": warn_count,
        "fail_count": fail_count,
    }
    if audit_messages:
        audit_payload["messages"] = list(audit_messages)
    metadata["audit"] = audit_payload
    return metadata


def _extract_replay_market_snapshot(
    base_metadata: Mapping[str, object] | None,
) -> JSONObject | None:
    if not isinstance(base_metadata, Mapping):
        return None
    raw = base_metadata.get(INTERNAL_REPLAY_MARKET_SNAPSHOT_KEY)
    if not isinstance(raw, Mapping):
        return None
    return dict(raw)


def _strip_internal_metadata(
    base_metadata: Mapping[str, object] | None,
) -> JSONObject:
    output: JSONObject = {}
    if not isinstance(base_metadata, Mapping):
        return output
    for key, value in base_metadata.items():
        if key == INTERNAL_REPLAY_MARKET_SNAPSHOT_KEY:
            continue
        output[key] = value
    return output


def _build_parameter_source_completion_fields(
    build_metadata: Mapping[str, object] | None,
) -> JSONObject:
    fields: JSONObject = {}
    if not isinstance(build_metadata, Mapping):
        fields["parameter_source_summary_present"] = False
        return fields

    parameter_source_raw = build_metadata.get("parameter_source_summary")
    has_parameter_source = isinstance(parameter_source_raw, Mapping)
    fields["parameter_source_summary_present"] = has_parameter_source
    if has_parameter_source:
        parameters_raw = parameter_source_raw.get("parameters")
        if isinstance(parameters_raw, Mapping):
            fields["parameter_source_parameter_count"] = len(parameters_raw)
            key_inputs = _extract_parameter_source_key_inputs(parameters_raw)
            if key_inputs:
                fields["parameter_source_key_inputs"] = key_inputs
                target_raw = key_inputs.get("target_mean_price")
                if isinstance(target_raw, Mapping):
                    source_count = target_raw.get("consensus_source_count")
                    sources = target_raw.get("consensus_sources")
                    analyst_total = target_raw.get("consensus_analyst_count_total")
                    if isinstance(source_count, int):
                        fields["target_consensus_source_count"] = source_count
                    if isinstance(sources, list) and sources:
                        fields["target_consensus_sources"] = list(sources)
                    if isinstance(analyst_total, int):
                        fields["target_consensus_analyst_count_total"] = analyst_total
        shares_raw = parameter_source_raw.get("shares_outstanding")
        if isinstance(shares_raw, Mapping):
            fallback_reason = shares_raw.get("fallback_reason")
            market_is_stale = shares_raw.get("market_is_stale")
            market_staleness_days = shares_raw.get("market_staleness_days")
            shares_scope = shares_raw.get("shares_scope")
            equity_value_scope = shares_raw.get("equity_value_scope")
            scope_mismatch_detected = shares_raw.get("scope_mismatch_detected")
            scope_mismatch_ratio = shares_raw.get("scope_mismatch_ratio")
            scope_mismatch_resolved = shares_raw.get("scope_mismatch_resolved")
            scope_policy_mode = shares_raw.get("scope_policy_mode")
            scope_policy_resolution = shares_raw.get("scope_policy_resolution")
            if isinstance(fallback_reason, str) and fallback_reason:
                fields["shares_fallback_reason"] = fallback_reason
            if isinstance(market_is_stale, bool):
                fields["shares_market_is_stale"] = market_is_stale
            if isinstance(market_staleness_days, int):
                fields["shares_market_staleness_days"] = market_staleness_days
            if isinstance(shares_scope, str) and shares_scope:
                fields["shares_scope"] = shares_scope
            if isinstance(equity_value_scope, str) and equity_value_scope:
                fields["equity_value_scope"] = equity_value_scope
            if isinstance(scope_mismatch_detected, bool):
                fields["shares_scope_mismatch_detected"] = scope_mismatch_detected
            if isinstance(scope_mismatch_ratio, int | float):
                fields["shares_scope_mismatch_ratio"] = float(scope_mismatch_ratio)
            if isinstance(scope_mismatch_resolved, bool):
                fields["shares_scope_mismatch_resolved"] = scope_mismatch_resolved
            if isinstance(scope_policy_mode, str) and scope_policy_mode:
                fields["shares_scope_policy_mode"] = scope_policy_mode
            if isinstance(scope_policy_resolution, str) and scope_policy_resolution:
                fields["shares_scope_policy_resolution"] = scope_policy_resolution

    data_freshness_raw = build_metadata.get("data_freshness")
    if not isinstance(data_freshness_raw, Mapping):
        return fields

    shares_source = data_freshness_raw.get("shares_outstanding_source")
    if isinstance(shares_source, str) and shares_source:
        fields["shares_outstanding_source"] = shares_source
    shares_path_raw = data_freshness_raw.get("shares_path")
    if isinstance(shares_path_raw, Mapping):
        shares_scope = shares_path_raw.get("shares_scope")
        equity_value_scope = shares_path_raw.get("equity_value_scope")
        scope_mismatch_detected = shares_path_raw.get("scope_mismatch_detected")
        scope_mismatch_ratio = shares_path_raw.get("scope_mismatch_ratio")
        scope_mismatch_resolved = shares_path_raw.get("scope_mismatch_resolved")
        scope_policy_mode = shares_path_raw.get("scope_policy_mode")
        scope_policy_resolution = shares_path_raw.get("scope_policy_resolution")
        if (
            isinstance(shares_scope, str)
            and shares_scope
            and "shares_scope" not in fields
        ):
            fields["shares_scope"] = shares_scope
        if (
            isinstance(equity_value_scope, str)
            and equity_value_scope
            and "equity_value_scope" not in fields
        ):
            fields["equity_value_scope"] = equity_value_scope
        if (
            isinstance(scope_mismatch_detected, bool)
            and "shares_scope_mismatch_detected" not in fields
        ):
            fields["shares_scope_mismatch_detected"] = scope_mismatch_detected
        if (
            isinstance(scope_mismatch_ratio, int | float)
            and "shares_scope_mismatch_ratio" not in fields
        ):
            fields["shares_scope_mismatch_ratio"] = float(scope_mismatch_ratio)
        if (
            isinstance(scope_mismatch_resolved, bool)
            and "shares_scope_mismatch_resolved" not in fields
        ):
            fields["shares_scope_mismatch_resolved"] = scope_mismatch_resolved
        if (
            isinstance(scope_policy_mode, str)
            and scope_policy_mode
            and "shares_scope_policy_mode" not in fields
        ):
            fields["shares_scope_policy_mode"] = scope_policy_mode
        if (
            isinstance(scope_policy_resolution, str)
            and scope_policy_resolution
            and "shares_scope_policy_resolution" not in fields
        ):
            fields["shares_scope_policy_resolution"] = scope_policy_resolution

    market_data_raw = data_freshness_raw.get("market_data")
    if isinstance(market_data_raw, Mapping):
        market_provider = market_data_raw.get("provider")
        market_as_of = market_data_raw.get("as_of")
        target_consensus_applied = market_data_raw.get("target_consensus_applied")
        target_consensus_source_count = market_data_raw.get(
            "target_consensus_source_count"
        )
        target_consensus_sources = market_data_raw.get("target_consensus_sources")
        target_consensus_fallback_reason = market_data_raw.get(
            "target_consensus_fallback_reason"
        )
        target_consensus_quality_bucket = market_data_raw.get(
            "target_consensus_quality_bucket"
        )
        target_consensus_confidence_weight = market_data_raw.get(
            "target_consensus_confidence_weight"
        )
        target_consensus_warnings = market_data_raw.get("target_consensus_warnings")
        target_consensus_warning_codes = market_data_raw.get(
            "target_consensus_warning_codes"
        )
        if isinstance(market_provider, str) and market_provider:
            fields["market_data_provider"] = market_provider
        if isinstance(market_as_of, str) and market_as_of:
            fields["market_data_as_of"] = market_as_of
        if isinstance(target_consensus_applied, bool):
            fields["target_consensus_applied"] = target_consensus_applied
        if isinstance(target_consensus_source_count, int):
            fields["target_consensus_source_count"] = target_consensus_source_count
        if isinstance(target_consensus_sources, list) and target_consensus_sources:
            parsed_sources = [
                item
                for item in target_consensus_sources
                if isinstance(item, str) and item
            ]
            if parsed_sources:
                fields["target_consensus_sources"] = parsed_sources
        if (
            isinstance(target_consensus_fallback_reason, str)
            and target_consensus_fallback_reason
        ):
            fields["target_consensus_fallback_reason"] = (
                target_consensus_fallback_reason
            )
        if (
            isinstance(target_consensus_quality_bucket, str)
            and target_consensus_quality_bucket
        ):
            fields["target_consensus_quality_bucket"] = target_consensus_quality_bucket
        if isinstance(target_consensus_confidence_weight, int | float):
            fields["target_consensus_confidence_weight"] = float(
                target_consensus_confidence_weight
            )
        if isinstance(target_consensus_warnings, list) and target_consensus_warnings:
            parsed_warnings = [
                item
                for item in target_consensus_warnings
                if isinstance(item, str) and item
            ]
            if parsed_warnings:
                fields["target_consensus_warnings"] = parsed_warnings
        if (
            isinstance(target_consensus_warning_codes, list)
            and target_consensus_warning_codes
        ):
            parsed_warning_codes = [
                item
                for item in target_consensus_warning_codes
                if isinstance(item, str) and item
            ]
            if parsed_warning_codes:
                fields["target_consensus_warning_codes"] = parsed_warning_codes

    financial_statement_raw = data_freshness_raw.get("financial_statement")
    if isinstance(financial_statement_raw, Mapping):
        filing_raw = financial_statement_raw.get("filing")
        if isinstance(filing_raw, Mapping):
            selection_mode = filing_raw.get("selection_mode")
            filing_date = filing_raw.get("filing_date")
            if isinstance(selection_mode, str) and selection_mode:
                fields["filing_selection_mode"] = selection_mode
            if isinstance(filing_date, str) and filing_date:
                fields["filing_date"] = filing_date

    return fields


def _extract_parameter_source_key_inputs(
    parameters_raw: Mapping[str, object],
) -> JSONObject:
    key_fields = (
        "current_price",
        "shares_outstanding",
        "risk_free_rate",
        "beta",
        "consensus_growth_rate",
        "long_run_growth_anchor",
        "target_mean_price",
    )
    output: JSONObject = {}
    for field in key_fields:
        datum_raw = parameters_raw.get(field)
        if not isinstance(datum_raw, Mapping):
            continue
        payload: JSONObject = {}
        value_raw = datum_raw.get("value")
        value = coerce_float(value_raw)
        if value is not None:
            payload["value"] = value
        elif value_raw is None:
            payload["value"] = None
        source_raw = datum_raw.get("source")
        if isinstance(source_raw, str) and source_raw:
            payload["source"] = source_raw
        staleness_raw = datum_raw.get("staleness")
        if isinstance(staleness_raw, Mapping):
            is_stale_raw = staleness_raw.get("is_stale")
            days_raw = staleness_raw.get("days")
            max_days_raw = staleness_raw.get("max_days")
            staleness_payload: JSONObject = {}
            if isinstance(is_stale_raw, bool):
                staleness_payload["is_stale"] = is_stale_raw
            if isinstance(days_raw, int):
                staleness_payload["days"] = days_raw
            if isinstance(max_days_raw, int):
                staleness_payload["max_days"] = max_days_raw
            if staleness_payload:
                payload["staleness"] = staleness_payload
        quality_flags_raw = datum_raw.get("quality_flags")
        if isinstance(quality_flags_raw, list):
            quality_flags = [
                item for item in quality_flags_raw if isinstance(item, str) and item
            ]
            if quality_flags:
                payload["quality_flags"] = quality_flags
        source_detail_raw = datum_raw.get("source_detail")
        if isinstance(source_detail_raw, str) and source_detail_raw:
            payload["source_detail"] = source_detail_raw
            if field == "target_mean_price":
                detail_kv = _parse_semicolon_key_values(source_detail_raw)
                source_count = _parse_optional_int(detail_kv.get("source_count"))
                if source_count is not None:
                    payload["consensus_source_count"] = source_count
                sources_raw = detail_kv.get("sources")
                if isinstance(sources_raw, str) and sources_raw:
                    sources = [
                        item.strip() for item in sources_raw.split(",") if item.strip()
                    ]
                    if sources:
                        payload["consensus_sources"] = sources
                analyst_total = _parse_optional_int(
                    detail_kv.get("analyst_count_total")
                )
                if analyst_total is not None:
                    payload["consensus_analyst_count_total"] = analyst_total
        if payload:
            output[field] = payload
    return output


def _parse_semicolon_key_values(raw: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for segment in raw.split(";"):
        key, sep, value = segment.partition("=")
        if not sep:
            continue
        normalized_key = key.strip()
        normalized_value = value.strip()
        if not normalized_key or not normalized_value:
            continue
        output[normalized_key] = normalized_value
    return output


def _parse_optional_int(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip()
        if not normalized:
            return None
        try:
            return int(float(normalized))
        except ValueError:
            return None
    return None


def _build_completion_quality_fields(
    *,
    build_metadata: Mapping[str, object] | None,
    assumptions: list[str],
    parameter_source_completion_fields: Mapping[str, object],
) -> JSONObject:
    reasons: list[str] = []

    if any(
        statement.startswith("terminal_growth fallback to filing-first anchor")
        or statement.startswith(
            "terminal_growth market anchor stale; fallback to policy default"
        )
        for statement in assumptions
    ):
        reasons.append("terminal_growth_market_stale_fallback")
    if any(
        statement.startswith("shares_outstanding fallback to filing (market stale")
        for statement in assumptions
    ):
        reasons.append("shares_market_stale_fallback")

    shares_fallback_reason = parameter_source_completion_fields.get(
        "shares_fallback_reason"
    )
    if shares_fallback_reason == "market_stale":
        reasons.append("shares_market_stale_fallback")
    shares_scope_mismatch_detected = parameter_source_completion_fields.get(
        "shares_scope_mismatch_detected"
    )
    shares_scope_mismatch_resolved = parameter_source_completion_fields.get(
        "shares_scope_mismatch_resolved"
    )
    if (
        isinstance(shares_scope_mismatch_detected, bool)
        and shares_scope_mismatch_detected
        and not (
            isinstance(shares_scope_mismatch_resolved, bool)
            and shares_scope_mismatch_resolved
        )
    ):
        reasons.append("shares_scope_mismatch")

    target_consensus_applied_raw = parameter_source_completion_fields.get(
        "target_consensus_applied"
    )
    target_consensus_fallback_reason_raw = parameter_source_completion_fields.get(
        "target_consensus_fallback_reason"
    )
    if (
        isinstance(target_consensus_applied_raw, bool)
        and not target_consensus_applied_raw
        and isinstance(target_consensus_fallback_reason_raw, str)
        and target_consensus_fallback_reason_raw
    ):
        reasons.append("target_consensus_fallback")
        reasons.append(
            f"target_consensus_fallback:{target_consensus_fallback_reason_raw}"
        )

    if isinstance(build_metadata, Mapping):
        missing_policy_raw = build_metadata.get("xbrl_missing_input_policy")
        if isinstance(missing_policy_raw, Mapping):
            downgraded_raw = missing_policy_raw.get("downgraded_to_warn")
            warn_only_raw = missing_policy_raw.get("warn_only_fields")
            if isinstance(downgraded_raw, bool) and downgraded_raw:
                reasons.append("xbrl_missing_non_critical_warn_only")
            if isinstance(warn_only_raw, list) and warn_only_raw:
                reasons.append("xbrl_missing_warn_only_fields_present")

        data_freshness_raw = build_metadata.get("data_freshness")
        if isinstance(data_freshness_raw, Mapping):
            market_data_raw = data_freshness_raw.get("market_data")
            if isinstance(market_data_raw, Mapping):
                source_warnings_raw = market_data_raw.get("source_warnings")
                if isinstance(source_warnings_raw, list):
                    source_warnings = [
                        item
                        for item in source_warnings_raw
                        if isinstance(item, str) and item
                    ]
                    if source_warnings:
                        reasons.append("market_data_source_warnings_present")
                target_consensus_warnings_raw = market_data_raw.get(
                    "target_consensus_warnings"
                )
                if isinstance(target_consensus_warnings_raw, list):
                    target_consensus_warnings = [
                        item
                        for item in target_consensus_warnings_raw
                        if isinstance(item, str) and item
                    ]
                    if target_consensus_warnings:
                        reasons.append("target_consensus_warnings_present")
                quality_flags_raw = market_data_raw.get("quality_flags")
                if isinstance(quality_flags_raw, list):
                    quality_flags = [
                        item
                        for item in quality_flags_raw
                        if isinstance(item, str) and item
                    ]
                    if quality_flags:
                        reasons.append("market_data_quality_flags_present")
                    if any("stale" in item for item in quality_flags):
                        reasons.append("market_data_stale")
                    if any("missing_api_key" in item for item in quality_flags):
                        reasons.append("market_data_missing_api_key")
                missing_fields_raw = market_data_raw.get("missing_fields")
                if isinstance(missing_fields_raw, list):
                    missing_fields = [
                        item
                        for item in missing_fields_raw
                        if isinstance(item, str) and item
                    ]
                    if missing_fields:
                        reasons.append("market_data_missing_fields_present")

    dedup_reasons = list(dict.fromkeys(reasons))
    fields: JSONObject = {"is_degraded": bool(dedup_reasons)}
    if dedup_reasons:
        fields["degrade_reasons"] = dedup_reasons
    return fields


def _extract_valuation_diagnostics_from_success_update(
    success_update: Mapping[str, object],
) -> JSONObject | None:
    artifact_raw = success_update.get("artifact")
    if not isinstance(artifact_raw, Mapping):
        return None
    preview_raw = artifact_raw.get("preview")
    if not isinstance(preview_raw, Mapping):
        return None
    diagnostics_raw = preview_raw.get("valuation_diagnostics")
    if not isinstance(diagnostics_raw, Mapping):
        return None
    return dict(diagnostics_raw)


def _build_valuation_snapshot_payload(
    *,
    execution_context,
    success_update: Mapping[str, object],
    params_dump: Mapping[str, object],
    calculation_metrics: Mapping[str, object],
    assumptions: list[str],
    build_metadata: Mapping[str, object] | None,
    replay_market_snapshot: Mapping[str, object] | None,
) -> JSONObject:
    payload: JSONObject = {
        "financial_reports": list(execution_context.reports_raw),
        "status": "done",
        "model_type": execution_context.model_type,
        "replay_schema_version": VALUATION_REPLAY_SCHEMA_VERSION,
        "replay_source_reports_artifact_id": execution_context.reports_artifact_id,
        "replay_params_dump": dict(params_dump),
        "replay_calculation_metrics": dict(calculation_metrics),
        "replay_assumptions": list(assumptions),
    }
    if execution_context.forward_signals is not None:
        signals_payload = serialize_forward_signals(execution_context.forward_signals)
        if signals_payload is not None:
            payload["forward_signals"] = signals_payload
    if isinstance(replay_market_snapshot, Mapping):
        payload["replay_market_snapshot"] = dict(replay_market_snapshot)
    if isinstance(build_metadata, Mapping):
        payload["replay_build_metadata"] = dict(build_metadata)

    diagnostics = _extract_valuation_diagnostics_from_success_update(success_update)
    if isinstance(diagnostics, Mapping):
        payload["valuation_diagnostics"] = dict(diagnostics)

    ticker = execution_context.ticker
    if isinstance(ticker, str) and ticker:
        payload["ticker"] = ticker

    company_profile_raw = execution_context.intent_ctx.get("company_profile")
    if isinstance(company_profile_raw, Mapping):
        name_raw = company_profile_raw.get("name")
        sector_raw = company_profile_raw.get("sector")
        industry_raw = company_profile_raw.get("industry")
        if isinstance(name_raw, str) and name_raw:
            payload["company_name"] = name_raw
        if isinstance(sector_raw, str) and sector_raw:
            payload["sector"] = sector_raw
        if isinstance(industry_raw, str) and industry_raw:
            payload["industry"] = industry_raw

    reasoning_raw = execution_context.fundamental.get("reasoning")
    if isinstance(reasoning_raw, str) and reasoning_raw:
        payload["reasoning"] = reasoning_raw

    return payload


def _rewrite_artifact_reference(
    artifact: Mapping[str, object],
    *,
    snapshot_artifact_id: str,
    reference_type: str,
) -> None:
    if not isinstance(artifact, dict):
        return
    artifact["reference"] = {
        "artifact_id": snapshot_artifact_id,
        "download_url": f"/api/artifacts/{snapshot_artifact_id}",
        "type": reference_type,
    }


def _apply_snapshot_artifact_reference(
    *,
    success_update: JSONObject,
    snapshot_artifact_id: str,
) -> None:
    reference_type = "financial_reports"

    artifact_raw = success_update.get("artifact")
    if isinstance(artifact_raw, Mapping):
        reference_raw = artifact_raw.get("reference")
        if isinstance(reference_raw, Mapping):
            type_raw = reference_raw.get("type")
            if isinstance(type_raw, str) and type_raw:
                reference_type = type_raw

    fundamental_raw = success_update.get("fundamental_analysis")
    if isinstance(fundamental_raw, dict):
        fundamental_raw["financial_reports_artifact_id"] = snapshot_artifact_id
        fa_artifact_raw = fundamental_raw.get("artifact")
        if isinstance(fa_artifact_raw, Mapping):
            reference_raw = fa_artifact_raw.get("reference")
            if isinstance(reference_raw, Mapping):
                type_raw = reference_raw.get("type")
                if isinstance(type_raw, str) and type_raw:
                    reference_type = type_raw
            _rewrite_artifact_reference(
                fa_artifact_raw,
                snapshot_artifact_id=snapshot_artifact_id,
                reference_type=reference_type,
            )

    if isinstance(artifact_raw, Mapping):
        _rewrite_artifact_reference(
            artifact_raw,
            snapshot_artifact_id=snapshot_artifact_id,
            reference_type=reference_type,
        )


def _extract_quality_gates(
    fundamental: Mapping[str, object],
) -> Mapping[str, object] | None:
    quality_raw = fundamental.get("xbrl_quality_gates")
    if isinstance(quality_raw, Mapping):
        return quality_raw
    fallback = fundamental.get("quality_gates")
    if isinstance(fallback, Mapping):
        return fallback
    return None


def _extract_blocking_quality_issues(
    quality_gates: Mapping[str, object] | None,
) -> list[Mapping[str, object]]:
    if not isinstance(quality_gates, Mapping):
        return []
    issues_raw = quality_gates.get("issues")
    if not isinstance(issues_raw, list):
        return []
    blocking: list[Mapping[str, object]] = []
    for raw in issues_raw:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("blocking") is True:
            blocking.append(raw)
    return blocking


def _is_quality_gate_blocked(quality_gates: Mapping[str, object] | None) -> bool:
    if not isinstance(quality_gates, Mapping):
        return False
    status_raw = quality_gates.get("status")
    if isinstance(status_raw, str) and status_raw.strip().lower() == "block":
        return True
    blocking_count = coerce_float(quality_gates.get("blocking_count"))
    return bool(blocking_count is not None and blocking_count > 0)


def _build_quality_gate_error_message(
    quality_gates: Mapping[str, object] | None,
    blocking_issues: list[Mapping[str, object]],
) -> str:
    if not blocking_issues:
        return f"{_XBRL_QUALITY_BLOCKED_CODE}: xbrl quality gate blocked valuation"
    first = blocking_issues[0]
    issue_code = first.get("code")
    issue_code_text = issue_code if isinstance(issue_code, str) else "QUALITY_BLOCK"
    field_key = first.get("field_key")
    field_label = field_key if isinstance(field_key, str) else "unknown_field"
    status = quality_gates.get("status") if isinstance(quality_gates, Mapping) else None
    status_text = status if isinstance(status, str) else "block"
    return (
        f"{_XBRL_QUALITY_BLOCKED_CODE}: status={status_text}, "
        f"issue_code={issue_code_text}, field={field_label}"
    )


def _quality_status_token(quality_gates: Mapping[str, object] | None) -> str:
    if not isinstance(quality_gates, Mapping):
        return "unknown"
    status_raw = quality_gates.get("status")
    if not isinstance(status_raw, str):
        return "unknown"
    token = status_raw.strip().lower()
    return token if token else "unknown"


def _apply_missing_input_policy(
    *,
    build_result: ParamBuildResult,
    quality_gates: Mapping[str, object] | None,
    model_type: str,
    ticker: str | None,
) -> ParamBuildResult:
    if not build_result.missing:
        return build_result

    quality_status = _quality_status_token(quality_gates)
    policy_result = apply_missing_metric_policy(
        missing_fields=build_result.missing,
        warn_only_fields=_WARN_ONLY_MISSING_INPUT_FIELDS,
    )
    downgraded_warn_only = bool(
        policy_result.warn_only_fields
    ) and not _is_quality_gate_blocked(quality_gates)
    blocking_fields = (
        policy_result.blocking_fields
        if downgraded_warn_only
        else list(build_result.missing)
    )

    metadata: JSONObject = {}
    if isinstance(build_result.metadata, Mapping):
        metadata.update(dict(build_result.metadata))
    metadata["xbrl_missing_input_policy"] = {
        "policy_version": "v1",
        "quality_status": quality_status,
        "blocking_fields": list(blocking_fields),
        "warn_only_fields": list(policy_result.warn_only_fields),
        "downgraded_to_warn": downgraded_warn_only,
    }

    assumptions = list(build_result.assumptions)
    if downgraded_warn_only:
        assumptions.append(
            "xbrl_missing_input_policy downgraded non-critical missing inputs to warn "
            f"(quality_status={quality_status}, "
            f"fields={sorted(set(policy_result.warn_only_fields))})"
        )
        log_event(
            logger,
            event="fundamental_valuation_missing_policy_applied",
            message="valuation missing-input policy downgraded warn-only fields",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_VALUATION_MISSING_INPUTS_WARN_ONLY",
            fields={
                "ticker": ticker,
                "model_type": model_type,
                "quality_status": quality_status,
                "warn_only_fields": list(policy_result.warn_only_fields),
                "blocking_fields": list(blocking_fields),
            },
        )

    return ParamBuildResult(
        params=build_result.params,
        trace_inputs=build_result.trace_inputs,
        missing=blocking_fields,
        assumptions=assumptions,
        metadata=metadata,
    )


def _extract_missing_input_policy_metadata(
    build_metadata: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if not isinstance(build_metadata, Mapping):
        return None
    policy_raw = build_metadata.get("xbrl_missing_input_policy")
    if not isinstance(policy_raw, Mapping):
        return None
    return policy_raw


async def run_valuation_flow(
    runtime: ValuationRuntime,
    state: Mapping[str, object],
    *,
    build_params_fn: Callable[
        [str, str | None, list[JSONObject], list[JSONObject] | None],
        ParamBuildResult,
    ],
    get_model_runtime_fn: Callable[[str], object | None],
) -> FundamentalNodeResult:
    log_event(
        logger,
        event="fundamental_valuation_started",
        message="fundamental valuation started",
    )

    try:
        execution_context = await resolve_valuation_execution_context(
            runtime=runtime,
            state=state,
            get_model_runtime_fn=get_model_runtime_fn,
        )
        model_type = execution_context.model_type
        ticker = execution_context.ticker
        quality_gates = _extract_quality_gates(execution_context.fundamental)
        if _is_quality_gate_blocked(quality_gates):
            blocking_issues = _extract_blocking_quality_issues(quality_gates)
            quality_error = _build_quality_gate_error_message(
                quality_gates,
                blocking_issues,
            )
            log_event(
                logger,
                event="fundamental_valuation_quality_blocked",
                message="xbrl quality gate blocked valuation",
                level=logging.ERROR,
                error_code=_XBRL_QUALITY_BLOCKED_CODE,
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    "quality_status": (
                        quality_gates.get("status")
                        if isinstance(quality_gates, Mapping)
                        else None
                    ),
                    "quality_blocking_count": (
                        quality_gates.get("blocking_count")
                        if isinstance(quality_gates, Mapping)
                        else None
                    ),
                    "quality_issues": [dict(issue) for issue in blocking_issues],
                },
            )
            log_event(
                logger,
                event="fundamental_valuation_completed",
                message="fundamental valuation completed",
                level=logging.ERROR,
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    "status": "error",
                    "is_degraded": True,
                    "error_code": _XBRL_QUALITY_BLOCKED_CODE,
                    "quality_blocking_count": len(blocking_issues),
                },
            )
            return FundamentalNodeResult(
                update=runtime.build_valuation_error_update(quality_error),
                goto="END",
            )

        def _build_params_with_missing_policy(
            model_type_raw: str,
            ticker_raw: str | None,
            reports_raw: list[JSONObject],
            forward_signals_raw: list[ForwardSignalPayload] | None,
        ) -> ParamBuildResult:
            base_result = build_params_fn(
                model_type_raw,
                ticker_raw,
                reports_raw,
                forward_signals_raw,
            )
            return _apply_missing_input_policy(
                build_result=base_result,
                quality_gates=quality_gates,
                model_type=model_type_raw,
                ticker=ticker_raw,
            )

        execution_result = await _offload_valuation_compute(
            execute_valuation_calculation,
            context=execution_context,
            build_params_fn=_build_params_with_missing_policy,
        )
        build_result = execution_result.build_result
        base_metadata = (
            build_result.metadata
            if isinstance(build_result.metadata, Mapping)
            else None
        )
        replay_market_snapshot = _extract_replay_market_snapshot(base_metadata)
        external_metadata = _strip_internal_metadata(base_metadata)
        build_metadata = _build_metadata_with_audit(
            base_metadata=external_metadata,
            audit_passed=execution_result.audit_passed,
            audit_messages=execution_result.audit_messages,
        )

        _log_build_result_policy_events(
            model_type=model_type,
            build_result=build_result,
        )

        if build_result.missing:
            missing_policy_meta = _extract_missing_input_policy_metadata(base_metadata)
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
                    "quality_status": _quality_status_token(quality_gates),
                    "missing_warn_only_fields": (
                        missing_policy_meta.get("warn_only_fields")
                        if isinstance(missing_policy_meta, Mapping)
                        else None
                    ),
                    "missing_policy_downgraded_to_warn": (
                        missing_policy_meta.get("downgraded_to_warn")
                        if isinstance(missing_policy_meta, Mapping)
                        else None
                    ),
                },
            )
            log_event(
                logger,
                event="fundamental_valuation_completed",
                message="fundamental valuation completed",
                level=logging.ERROR,
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    "status": "error",
                    "is_degraded": True,
                    "error_code": "FUNDAMENTAL_VALUATION_INPUTS_MISSING",
                    "missing_input_count": len(build_result.missing),
                    "quality_status": _quality_status_token(quality_gates),
                },
            )
            return FundamentalNodeResult(
                update=runtime.build_valuation_missing_inputs_update(
                    fundamental=execution_context.fundamental,
                    missing_inputs=build_result.missing,
                    assumptions=build_result.assumptions,
                ),
                goto="END",
            )

        if execution_result.audit_error:
            log_event(
                logger,
                event="fundamental_valuation_audit_failed",
                message="valuation audit rejected parameter set",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_VALUATION_AUDIT_FAILED",
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    "error": execution_result.audit_error,
                    "audit_message_count": len(execution_result.audit_messages),
                    "audit_messages": execution_result.audit_messages,
                },
            )
            log_event(
                logger,
                event="fundamental_valuation_completed",
                message="fundamental valuation completed",
                level=logging.ERROR,
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    "status": "error",
                    "is_degraded": True,
                    "error_code": "FUNDAMENTAL_VALUATION_AUDIT_FAILED",
                    "audit_message_count": len(execution_result.audit_messages),
                },
            )
            return FundamentalNodeResult(
                update=runtime.build_valuation_error_update(
                    execution_result.audit_error
                ),
                goto="END",
            )

        audit_warn_count = len(
            [
                item
                for item in execution_result.audit_messages
                if item.startswith("WARN:")
            ]
        )
        if audit_warn_count > 0:
            log_event(
                logger,
                event="fundamental_valuation_audit_warnings",
                message="valuation audit emitted warnings",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_VALUATION_AUDIT_WARNINGS",
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    "audit_warn_count": audit_warn_count,
                    "audit_message_count": len(execution_result.audit_messages),
                    "audit_messages": execution_result.audit_messages,
                },
            )

        if execution_result.calculation_error:
            log_event(
                logger,
                event="fundamental_valuation_calculation_error",
                message="valuation calculator returned error payload",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_VALUATION_CALCULATION_ERROR",
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    "error": execution_result.calculation_error,
                },
            )
            log_event(
                logger,
                event="fundamental_valuation_completed",
                message="fundamental valuation completed",
                level=logging.ERROR,
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    "status": "error",
                    "is_degraded": True,
                    "error_code": "FUNDAMENTAL_VALUATION_CALCULATION_ERROR",
                },
            )
            return FundamentalNodeResult(
                update=runtime.build_valuation_error_update(
                    execution_result.calculation_error
                ),
                goto="END",
            )

        params_dump = execution_result.params_dump
        calculation_metrics = execution_result.calculation_metrics
        if params_dump is None or calculation_metrics is None:
            raise RuntimeError(
                "valuation calculation result is missing params_dump or metrics"
            )

        valuation_snapshot_fields = _build_valuation_metrics_snapshot_fields(
            params_dump=params_dump,
            calculation_metrics=calculation_metrics,
            assumptions=build_result.assumptions,
        )
        if valuation_snapshot_fields:
            log_event(
                logger,
                event="fundamental_valuation_metrics_snapshot",
                message="fundamental valuation metrics snapshot recorded",
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    **valuation_snapshot_fields,
                },
            )
            mismatch_reason = _detect_valuation_metric_mismatch(
                valuation_snapshot_fields
            )
            if mismatch_reason is not None:
                log_event(
                    logger,
                    event="fundamental_valuation_metric_mismatch",
                    message=(
                        "point valuation and distribution metrics are materially "
                        "inconsistent"
                    ),
                    level=logging.WARNING,
                    error_code="FUNDAMENTAL_VALUATION_METRIC_MISMATCH",
                    fields={
                        "ticker": ticker,
                        "model_type": model_type,
                        "mismatch_reason": mismatch_reason,
                        **valuation_snapshot_fields,
                    },
                )

        mc_completion_fields = build_monte_carlo_completion_fields(calculation_metrics)
        forward_signal_completion_fields = build_forward_signal_completion_fields(
            forward_signals=execution_context.forward_signals,
            build_metadata=build_metadata,
        )
        parameter_source_completion_fields = _build_parameter_source_completion_fields(
            build_metadata if isinstance(build_metadata, Mapping) else None,
        )
        completion_quality_fields = _build_completion_quality_fields(
            build_metadata=build_metadata
            if isinstance(build_metadata, Mapping)
            else None,
            assumptions=build_result.assumptions,
            parameter_source_completion_fields=parameter_source_completion_fields,
        )
        log_event(
            logger,
            event="fundamental_valuation_completed",
            message="fundamental valuation completed",
            fields={
                "ticker": ticker,
                "model_type": model_type,
                "status": "done",
                "audit_passed": execution_result.audit_passed is True,
                "audit_message_count": len(execution_result.audit_messages),
                **mc_completion_fields,
                **forward_signal_completion_fields,
                **parameter_source_completion_fields,
                **completion_quality_fields,
            },
        )

        success_update = runtime.build_valuation_success_update(
            fundamental=execution_context.fundamental,
            intent_ctx=execution_context.intent_ctx,
            ticker=ticker,
            model_type=model_type,
            reports_raw=execution_context.reports_raw,
            reports_artifact_id=execution_context.reports_artifact_id,
            params_dump=params_dump,
            calculation_metrics=calculation_metrics,
            assumptions=build_result.assumptions,
            build_metadata=build_metadata,
        )

        snapshot_payload = _build_valuation_snapshot_payload(
            execution_context=execution_context,
            success_update=success_update,
            params_dump=params_dump,
            calculation_metrics=calculation_metrics,
            assumptions=build_result.assumptions,
            build_metadata=build_metadata,
            replay_market_snapshot=replay_market_snapshot,
        )
        try:
            snapshot_artifact_id = await runtime.save_financial_reports(
                data=snapshot_payload,
                produced_by="fundamental_analysis.valuation",
                key_prefix="valuation",
            )
            _apply_snapshot_artifact_reference(
                success_update=success_update,
                snapshot_artifact_id=snapshot_artifact_id,
            )
            log_event(
                logger,
                event="fundamental_valuation_snapshot_saved",
                message="valuation snapshot artifact saved",
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    "snapshot_artifact_id": snapshot_artifact_id,
                },
            )
        except Exception as exc:
            log_event(
                logger,
                event="fundamental_valuation_snapshot_save_failed",
                message="valuation snapshot artifact save failed",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_VALUATION_SNAPSHOT_SAVE_FAILED",
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    "exception": str(exc),
                },
            )

        return FundamentalNodeResult(update=success_update, goto="END")
    except Exception as exc:
        log_event(
            logger,
            event="fundamental_valuation_failed",
            message="fundamental valuation failed",
            level=logging.ERROR,
            error_code="FUNDAMENTAL_VALUATION_FAILED",
            fields={"exception": str(exc)},
        )
        log_event(
            logger,
            event="fundamental_valuation_completed",
            message="fundamental valuation completed",
            level=logging.ERROR,
            fields={
                "status": "error",
                "is_degraded": True,
                "error_code": "FUNDAMENTAL_VALUATION_FAILED",
            },
        )
        return FundamentalNodeResult(
            update=runtime.build_valuation_error_update(str(exc)),
            goto="END",
        )
