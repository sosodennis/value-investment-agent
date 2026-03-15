from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import Protocol

import pandas as pd

from src.agents.technical.application.state_readers import (
    resolved_ticker_from_state,
    technical_state_from_state,
)
from src.agents.technical.application.state_updates import (
    build_verification_compute_error_update,
    build_verification_compute_success_update,
)
from src.agents.technical.domain.shared import PriceSeries
from src.agents.technical.interface.serializers import (
    build_verification_compute_preview,
    build_verification_report_payload,
)
from src.agents.technical.subdomains.features.domain import (
    calculate_fd_bollinger,
    calculate_fd_macd,
    calculate_fd_obv,
    calculate_rolling_fracdiff,
    calculate_rolling_z_score,
    calculate_statistical_strength,
    compute_z_score,
    serialize_fracdiff_outputs,
)
from src.agents.technical.subdomains.verification import (
    VerificationRuntimeRequest,
    VerificationRuntimeResult,
    VerificationRuntimeService,
    evaluate_verification_baseline,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalTimeseriesBundleArtifactData,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
TechnicalNodeResult = WorkflowNodeResult


class VerificationComputeRuntime(Protocol):
    async def load_timeseries_bundle(
        self, artifact_id: str
    ) -> TechnicalTimeseriesBundleArtifactData | None: ...

    async def save_chart_data(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def save_verification_report(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]


async def run_verification_compute_use_case(
    runtime: VerificationComputeRuntime,
    state: Mapping[str, object],
    *,
    verification_runtime: VerificationRuntimeService,
) -> TechnicalNodeResult:
    ticker_value = resolved_ticker_from_state(state)
    log_event(
        logger,
        event="technical_verification_compute_started",
        message="technical verification compute started",
        fields={"ticker": ticker_value},
    )

    technical_context = technical_state_from_state(state)
    timeseries_bundle_id = technical_context.timeseries_bundle_id
    feature_pack_id = technical_context.feature_pack_id
    fusion_report_id = technical_context.fusion_report_id

    if (
        timeseries_bundle_id is None
        or feature_pack_id is None
        or fusion_report_id is None
    ):
        log_event(
            logger,
            event="technical_verification_missing_inputs",
            message="technical verification compute missing required inputs",
            level=logging.ERROR,
            error_code="TECHNICAL_VERIFICATION_INPUTS_MISSING",
            fields={
                "ticker": ticker_value,
                "timeseries_bundle_id": timeseries_bundle_id,
                "feature_pack_id": feature_pack_id,
                "fusion_report_id": fusion_report_id,
            },
        )
        log_event(
            logger,
            event="technical_verification_compute_completed",
            message="technical verification compute completed",
            level=logging.ERROR,
            fields={
                "ticker": ticker_value,
                "status": "error",
                "is_degraded": True,
                "error_code": "TECHNICAL_VERIFICATION_INPUTS_MISSING",
                "input_count": 0,
                "output_count": 0,
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_verification_compute_error_update(
                "Missing timeseries/feature/fusion inputs"
            ),
            goto="END",
        )

    chart_data_id: str | None = None
    try:
        bundle = await runtime.load_timeseries_bundle(timeseries_bundle_id)
        if bundle is None:
            log_event(
                logger,
                event="technical_verification_bundle_not_found",
                message="technical verification compute failed due to missing timeseries bundle",
                level=logging.ERROR,
                error_code="TECHNICAL_TIMESERIES_BUNDLE_NOT_FOUND",
                fields={
                    "ticker": ticker_value,
                    "timeseries_bundle_id": timeseries_bundle_id,
                },
            )
            log_event(
                logger,
                event="technical_verification_compute_completed",
                message="technical verification compute completed",
                level=logging.ERROR,
                fields={
                    "ticker": ticker_value,
                    "status": "error",
                    "is_degraded": True,
                    "error_code": "TECHNICAL_TIMESERIES_BUNDLE_NOT_FOUND",
                    "input_count": 0,
                    "output_count": 0,
                    "artifact_written": False,
                },
            )
            return TechnicalNodeResult(
                update=build_verification_compute_error_update(
                    "Timeseries bundle not found in store"
                ),
                goto="END",
            )

        series_by_timeframe: dict[str, PriceSeries] = {}
        for timeframe, frame in bundle.frames.items():
            series_by_timeframe[timeframe] = PriceSeries(
                timeframe=timeframe,
                start=frame.start,
                end=frame.end,
                price_series=frame.price_series,
                volume_series=frame.volume_series,
                timezone=frame.timezone,
                metadata=frame.metadata or {},
            )
        input_count = len(series_by_timeframe)

        anchor_timeframe = "1d" if "1d" in series_by_timeframe else None
        if anchor_timeframe is None and series_by_timeframe:
            anchor_timeframe = next(iter(series_by_timeframe))

        if anchor_timeframe is None:
            raise ValueError("No timeseries frames available")

        anchor_series = series_by_timeframe[anchor_timeframe]

        def _compute_verification():
            price_series = _build_series(anchor_series.price_series)
            volume_series = _build_series(anchor_series.volume_series)

            if price_series.empty:
                return (
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )

            fd_series, optimal_d, window_length, adf_stat, adf_pvalue = (
                calculate_rolling_fracdiff(
                    price_series,
                    lookback_window=252,
                    recalc_step=5,
                )
            )
            if fd_series.empty:
                return (
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )

            z_score_latest = compute_z_score(fd_series, lookback=252)
            z_score_series = calculate_rolling_z_score(fd_series, lookback=252)
            stat_strength = calculate_statistical_strength(z_score_series)
            bollinger = calculate_fd_bollinger(fd_series)
            obv = calculate_fd_obv(price_series, volume_series)
            macd = calculate_fd_macd(fd_series)

            verification_request = VerificationRuntimeRequest(
                ticker=bundle.ticker,
                as_of=bundle.as_of,
                price_series=price_series,
                z_score_series=z_score_series,
                stat_strength_dict=stat_strength,
                obv_dict=obv,
                bollinger_dict=bollinger,
                rf_series=None,
            )
            verification_result = verification_runtime.compute(verification_request)
            latest_price = (
                float(price_series.iloc[-1]) if not price_series.empty else None
            )

            serialization = serialize_fracdiff_outputs(
                fd_series=fd_series,
                z_score_series=z_score_series,
                bollinger_data=bollinger,
                stat_strength_data=stat_strength,
                obv_data=obv,
            )
            chart_payload = {
                "fracdiff_series": serialization.fracdiff_series,
                "z_score_series": serialization.z_score_series,
                "indicators": {
                    "bollinger": serialization.bollinger.to_dict(),
                    "obv": serialization.obv.to_dict(),
                },
            }
            return (
                verification_result,
                latest_price,
                _safe_float(optimal_d),
                _safe_float(z_score_latest),
                int(window_length),
                _safe_float(adf_stat),
                _safe_float(adf_pvalue),
                bollinger,
                stat_strength,
                macd,
                obv,
                chart_payload,
            )

        (
            verification_result,
            latest_price,
            optimal_d,
            z_score_latest,
            window_length,
            adf_stat,
            adf_pvalue,
            bollinger,
            stat_strength,
            macd,
            obv,
            chart_payload,
        ) = await asyncio.to_thread(_compute_verification)

        degraded_reasons: list[str] = []
        if verification_result is None:
            degraded_reasons.append("VERIFICATION_INPUTS_INSUFFICIENT")
            baseline_gates = evaluate_verification_baseline(
                backtest_summary=None,
                wfa_summary=None,
            )
            verification_result = VerificationRuntimeResult(
                backtest_summary=None,
                wfa_summary=None,
                baseline_gates=baseline_gates,
                robustness_flags=[],
                degraded_reasons=degraded_reasons,
            )
        else:
            degraded_reasons.extend(verification_result.degraded_reasons)

        report_payload = build_verification_report_payload(
            ticker=bundle.ticker,
            as_of=bundle.as_of,
            backtest_summary=verification_result.backtest_summary,
            wfa_summary=verification_result.wfa_summary,
            baseline_gates=verification_result.baseline_gates,
            robustness_flags=verification_result.robustness_flags,
            source_artifacts={
                "timeseries_bundle_id": timeseries_bundle_id,
                "feature_pack_id": feature_pack_id,
                "fusion_report_id": fusion_report_id,
            },
            degraded_reasons=degraded_reasons,
        )

        if chart_payload is not None:
            chart_data_id = await runtime.save_chart_data(
                data=chart_payload,
                produced_by="technical_analysis.verification_compute",
                key_prefix=ticker_value,
            )

        verification_report_id = await runtime.save_verification_report(
            data=report_payload,
            produced_by="technical_analysis.verification_compute",
            key_prefix=ticker_value,
        )
    except Exception as exc:
        log_event(
            logger,
            event="technical_verification_compute_failed",
            message="technical verification compute failed",
            level=logging.ERROR,
            error_code="TECHNICAL_VERIFICATION_COMPUTE_FAILED",
            fields={"ticker": ticker_value, "exception": str(exc)},
        )
        log_event(
            logger,
            event="technical_verification_compute_completed",
            message="technical verification compute completed",
            level=logging.ERROR,
            fields={
                "ticker": ticker_value,
                "status": "error",
                "is_degraded": True,
                "error_code": "TECHNICAL_VERIFICATION_COMPUTE_FAILED",
                "input_count": 0,
                "output_count": 0,
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_verification_compute_error_update(
                f"Verification compute failed: {str(exc)}"
            ),
            goto="END",
        )

    preview = build_verification_compute_preview(
        ticker=ticker_value or "N/A",
        baseline_status=verification_result.baseline_gates.status,
        trade_count=(
            verification_result.backtest_summary.total_trades
            if verification_result.backtest_summary is not None
            else 0
        ),
        wfe_ratio=(
            verification_result.wfa_summary.wfe_ratio
            if verification_result.wfa_summary is not None
            else None
        ),
    )
    artifact = runtime.build_progress_artifact(
        f"Technical Analysis: Verification computed for {ticker_value or 'N/A'}",
        preview,
    )
    output_count = 1 + (1 if chart_data_id is not None else 0)
    if degraded_reasons:
        log_event(
            logger,
            event="technical_verification_compute_degraded",
            message="technical verification compute completed with degraded quality",
            level=logging.WARNING,
            error_code="TECHNICAL_VERIFICATION_DEGRADED",
            fields={
                "ticker": ticker_value,
                "degrade_source": "verification_runtime",
                "fallback_mode": "continue_with_verification_report",
                "degraded_reasons": degraded_reasons,
                "input_count": input_count,
                "output_count": output_count,
            },
        )
    log_event(
        logger,
        event="technical_verification_compute_completed",
        message="technical verification compute completed",
        fields={
            "ticker": ticker_value,
            "status": "done",
            "is_degraded": bool(degraded_reasons),
            "verification_report_id": verification_report_id,
            "chart_data_id": chart_data_id,
            "input_count": input_count,
            "output_count": output_count,
            "artifact_written": True,
        },
    )

    return TechnicalNodeResult(
        update=build_verification_compute_success_update(
            verification_report_id=verification_report_id,
            chart_data_id=chart_data_id,
            latest_price=latest_price,
            optimal_d=optimal_d,
            z_score_latest=z_score_latest,
            window_length=window_length,
            adf_statistic=adf_stat,
            adf_pvalue=adf_pvalue,
            bollinger=_strip_series(bollinger),
            statistical_strength_val=(
                float(stat_strength.get("value"))
                if isinstance(stat_strength, dict)
                else None
            ),
            macd=_strip_series(macd),
            obv=_strip_series(obv),
            artifact=artifact,
        ),
        goto="semantic_translate",
    )


def _build_series(raw_series: dict[str, float | int | None]) -> pd.Series:
    if not raw_series:
        return pd.Series(dtype=float)
    series = pd.Series(raw_series)
    try:
        series.index = pd.to_datetime(series.index)
    except Exception:
        pass
    return series.sort_index().dropna()


def _strip_series(data: object) -> dict[str, float | str | None]:
    if not isinstance(data, dict):
        return {}
    stripped: dict[str, float | str | None] = {}
    for key, value in data.items():
        if isinstance(value, pd.Series):
            continue
        if isinstance(value, float | int):
            stripped[key] = float(value)
        elif isinstance(value, str):
            stripped[key] = value
    return stripped


def _safe_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
