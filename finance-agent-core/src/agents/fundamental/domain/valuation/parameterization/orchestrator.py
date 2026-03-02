from __future__ import annotations

from collections.abc import Mapping

from src.shared.kernel.tools.logger import get_logger, log_event

from ..report_contract import (
    FinancialReport,
    parse_domain_financial_reports,
)
from .contracts import ParamBuildResult
from .core_ops_service import (
    sort_reports_by_year_desc as _sort_reports_by_year_desc,
)
from .policy_service import (
    apply_forward_signal_adjustments as _apply_forward_signal_adjustments_service,
)
from .policy_service import (
    apply_time_alignment_guard as _apply_time_alignment_guard_service,
)
from .registry_service import (
    get_model_builder as _get_model_builder_service,
)

logger = get_logger(__name__)


DEFAULT_TIME_ALIGNMENT_MAX_DAYS = 365
DEFAULT_TIME_ALIGNMENT_POLICY = "warn"


def build_params(
    model_type: str,
    ticker: str | None,
    reports_raw: list[Mapping[str, object]] | None,
    market_snapshot: Mapping[str, object] | None = None,
) -> ParamBuildResult:
    log_event(
        logger,
        event="valuation_params_build_started",
        message="valuation parameter build started",
        fields={
            "model_type": model_type,
            "ticker": ticker,
            "input_reports_count": len(reports_raw or []),
        },
    )
    reports = parse_domain_financial_reports(reports_raw or [])
    if not reports:
        log_event(
            logger,
            event="valuation_params_build_failed",
            message="valuation parameter build failed due to missing reports",
            fields={"model_type": model_type, "ticker": ticker},
        )
        raise ValueError("No SEC XBRL financial reports available")

    reports_sorted = _sort_reports_by_year_desc(reports)
    latest = reports_sorted[0]

    model_builder = _get_model_builder_service(model_type)
    if model_builder is None:
        log_event(
            logger,
            event="valuation_params_build_failed",
            message="valuation parameter build failed due to unsupported model",
            fields={"model_type": model_type, "ticker": ticker},
        )
        raise ValueError(f"Unsupported model type for SEC XBRL builder: {model_type}")
    result = model_builder(
        ticker,
        latest,
        reports_sorted,
        market_snapshot=market_snapshot,
    )
    result = _apply_time_alignment_guard(
        result=result,
        latest=latest,
        market_snapshot=market_snapshot,
    )
    result = _apply_forward_signal_adjustments(
        result=result,
        model_type=model_type,
        market_snapshot=market_snapshot,
    )

    log_event(
        logger,
        event="valuation_params_build_completed",
        message="valuation parameter build completed",
        fields={
            "model_type": model_type,
            "ticker": ticker,
            "missing_count": len(result.missing),
            "assumptions_count": len(result.assumptions),
            "trace_input_count": len(result.trace_inputs),
        },
    )
    return result


def _apply_time_alignment_guard(
    *,
    result: ParamBuildResult,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    if market_snapshot is None:
        return result

    assumptions, metadata = _apply_time_alignment_guard_service(
        assumptions=result.assumptions,
        metadata=result.metadata,
        period_end_raw=latest.base.period_end_date.value,
        market_snapshot=market_snapshot,
        default_threshold_days=DEFAULT_TIME_ALIGNMENT_MAX_DAYS,
        default_policy=DEFAULT_TIME_ALIGNMENT_POLICY,
    )
    if assumptions == result.assumptions and metadata == result.metadata:
        return result

    return ParamBuildResult(
        params=result.params,
        trace_inputs=result.trace_inputs,
        missing=result.missing,
        assumptions=assumptions,
        metadata=metadata,
    )


def _apply_forward_signal_adjustments(
    *,
    result: ParamBuildResult,
    model_type: str,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    if market_snapshot is None:
        return result

    raw_signals = market_snapshot.get("forward_signals")
    if raw_signals is None:
        return result

    outcome = _apply_forward_signal_adjustments_service(
        params=result.params,
        assumptions=result.assumptions,
        metadata=result.metadata,
        model_type=model_type,
        raw_signals=raw_signals,
    )
    if outcome.log_fields is not None:
        log_event(
            logger,
            event="valuation_forward_signal_policy_applied",
            message="forward signal policy applied to valuation params",
            fields=outcome.log_fields,
        )
    return ParamBuildResult(
        params=outcome.params,
        trace_inputs=result.trace_inputs,
        missing=result.missing,
        assumptions=outcome.assumptions,
        metadata=outcome.metadata,
    )
