from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import Protocol

from src.agents.fundamental.application.services.valuation_completion_fields_service import (
    build_forward_signal_completion_fields,
    build_monte_carlo_completion_fields,
)
from src.agents.fundamental.application.services.valuation_distribution_preview_service import (
    coerce_float,
    extract_distribution_summary,
)
from src.agents.fundamental.application.services.valuation_execution_context_service import (
    resolve_valuation_execution_context,
)
from src.agents.fundamental.application.services.valuation_execution_result_service import (
    execute_valuation_calculation,
)
from src.agents.fundamental.domain.valuation.parameterization.contracts import (
    ParamBuildResult,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
FundamentalNodeResult = WorkflowNodeResult
_VALUATION_COMPUTE_CONCURRENCY_LIMIT = 2
_valuation_compute_semaphore: asyncio.Semaphore | None = None


class ValuationRuntime(Protocol):
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


def _build_valuation_metrics_snapshot_fields(
    *,
    params_dump: Mapping[str, object],
    calculation_metrics: Mapping[str, object],
) -> JSONObject:
    fields: JSONObject = {}

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

    # Preserve metric type even when summary is missing so downstream triage is simpler.
    if distribution_metric_type is None and isinstance(distribution_summary, Mapping):
        fields["distribution_metric_type"] = "unknown"

    return fields


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
        if isinstance(forward_signal_raw, Mapping):
            log_event(
                logger,
                event="fundamental_forward_signal_policy_applied",
                message="forward signal policy summary recorded",
                fields={
                    "model_type": model_type,
                    "signals_total": forward_signal_raw.get("signals_total"),
                    "signals_accepted": forward_signal_raw.get("signals_accepted"),
                    "signals_rejected": forward_signal_raw.get("signals_rejected"),
                    "growth_adjustment_basis_points": forward_signal_raw.get(
                        "growth_adjustment_basis_points"
                    ),
                    "margin_adjustment_basis_points": forward_signal_raw.get(
                        "margin_adjustment_basis_points"
                    ),
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
        shares_raw = parameter_source_raw.get("shares_outstanding")
        if isinstance(shares_raw, Mapping):
            fallback_reason = shares_raw.get("fallback_reason")
            market_is_stale = shares_raw.get("market_is_stale")
            market_staleness_days = shares_raw.get("market_staleness_days")
            if isinstance(fallback_reason, str) and fallback_reason:
                fields["shares_fallback_reason"] = fallback_reason
            if isinstance(market_is_stale, bool):
                fields["shares_market_is_stale"] = market_is_stale
            if isinstance(market_staleness_days, int):
                fields["shares_market_staleness_days"] = market_staleness_days

    data_freshness_raw = build_metadata.get("data_freshness")
    if not isinstance(data_freshness_raw, Mapping):
        return fields

    shares_source = data_freshness_raw.get("shares_outstanding_source")
    if isinstance(shares_source, str) and shares_source:
        fields["shares_outstanding_source"] = shares_source

    market_data_raw = data_freshness_raw.get("market_data")
    if isinstance(market_data_raw, Mapping):
        market_provider = market_data_raw.get("provider")
        market_as_of = market_data_raw.get("as_of")
        if isinstance(market_provider, str) and market_provider:
            fields["market_data_provider"] = market_provider
        if isinstance(market_as_of, str) and market_as_of:
            fields["market_data_as_of"] = market_as_of

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


def _build_completion_quality_fields(
    *,
    build_metadata: Mapping[str, object] | None,
    assumptions: list[str],
    parameter_source_completion_fields: Mapping[str, object],
) -> JSONObject:
    reasons: list[str] = []

    if any(
        statement.startswith("terminal_growth fallback to filing-first anchor")
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

    if isinstance(build_metadata, Mapping):
        data_freshness_raw = build_metadata.get("data_freshness")
        if isinstance(data_freshness_raw, Mapping):
            market_data_raw = data_freshness_raw.get("market_data")
            if isinstance(market_data_raw, Mapping):
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

    dedup_reasons = list(dict.fromkeys(reasons))
    fields: JSONObject = {"is_degraded": bool(dedup_reasons)}
    if dedup_reasons:
        fields["degrade_reasons"] = dedup_reasons
    return fields


async def run_valuation_use_case(
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

        execution_result = await _offload_valuation_compute(
            execute_valuation_calculation,
            context=execution_context,
            build_params_fn=build_params_fn,
        )
        build_result = execution_result.build_result
        build_metadata = _build_metadata_with_audit(
            base_metadata=(
                build_result.metadata
                if isinstance(build_result.metadata, Mapping)
                else None
            ),
            audit_passed=execution_result.audit_passed,
            audit_messages=execution_result.audit_messages,
        )

        _log_build_result_policy_events(
            model_type=model_type,
            build_result=build_result,
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

        return FundamentalNodeResult(
            update=runtime.build_valuation_success_update(
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
