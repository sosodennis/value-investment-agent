from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import pandas as pd
from langchain_core.messages import AIMessage

from src.agents.technical.application.report_service import (
    build_semantic_report_update,
)
from src.agents.technical.application.semantic_service import (
    execute_semantic_pipeline,
)
from src.agents.technical.application.state_readers import (
    resolved_ticker_from_state,
    technical_state_from_state,
)
from src.agents.technical.application.state_updates import (
    build_data_fetch_error_update,
    build_data_fetch_success_update,
    build_fracdiff_error_update,
    build_fracdiff_success_update,
    build_semantic_error_update,
    build_semantic_success_update,
)
from src.agents.technical.data.mappers import serialize_fracdiff_outputs
from src.agents.technical.data.ports import TechnicalArtifactPort
from src.agents.technical.domain.models import (
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)
from src.agents.technical.domain.services import safe_float
from src.agents.technical.interface.serializers import (
    build_data_fetch_preview,
    build_fracdiff_progress_preview,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

logger = get_logger(__name__)


@dataclass(frozen=True)
class TechnicalNodeResult:
    update: dict[str, object]
    goto: str


@dataclass(frozen=True)
class TechnicalOrchestrator:
    port: TechnicalArtifactPort
    summarize_preview: Callable[[JSONObject], JSONObject]
    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]
    build_semantic_output_artifact: Callable[[str, JSONObject, str], dict[str, object]]

    async def run_data_fetch(
        self,
        state: Mapping[str, object],
        *,
        fetch_daily_ohlcv_fn: Callable[[str], pd.DataFrame],
    ) -> TechnicalNodeResult:
        resolved_ticker = resolved_ticker_from_state(state)
        if resolved_ticker is None:
            log_event(
                logger,
                event="technical_data_fetch_missing_ticker",
                message="technical data fetch skipped due to missing resolved ticker",
                level=logging.ERROR,
                error_code="TECHNICAL_TICKER_MISSING",
            )
            return TechnicalNodeResult(
                update=build_data_fetch_error_update("No resolved ticker available"),
                goto="END",
            )

        log_event(
            logger,
            event="technical_data_fetch_started",
            message="technical data fetch started",
            fields={"ticker": resolved_ticker},
        )

        try:
            df = fetch_daily_ohlcv_fn(resolved_ticker)
        except Exception as exc:
            log_event(
                logger,
                event="technical_data_fetch_failed",
                message="technical data fetch failed",
                level=logging.ERROR,
                error_code="TECHNICAL_DATA_FETCH_FAILED",
                fields={"ticker": resolved_ticker, "exception": str(exc)},
            )
            return TechnicalNodeResult(
                update=build_data_fetch_error_update(f"Data fetch failed: {str(exc)}"),
                goto="END",
            )

        if df is None or df.empty:
            log_event(
                logger,
                event="technical_data_fetch_empty",
                message="technical data fetch returned empty frame",
                level=logging.WARNING,
                error_code="TECHNICAL_DATA_EMPTY",
                fields={"ticker": resolved_ticker},
            )
            return TechnicalNodeResult(
                update=build_data_fetch_error_update(
                    "Empty data returned from provider"
                ),
                goto="END",
            )

        price_series = df["price"].rename(index=lambda x: x.strftime("%Y-%m-%d"))
        volume_series = df["volume"].rename(index=lambda x: x.strftime("%Y-%m-%d"))
        price_data = {
            "price_series": price_series.astype(object)
            .where(pd.notnull(price_series), None)
            .to_dict(),
            "volume_series": volume_series.astype(object)
            .where(pd.notnull(volume_series), None)
            .to_dict(),
        }

        price_artifact_id = await self.port.save_price_series(
            data=price_data,
            produced_by="technical_analysis.data_fetch",
            key_prefix=resolved_ticker,
        )

        preview = build_data_fetch_preview(
            ticker=resolved_ticker,
            latest_price=df["price"].iloc[-1],
        )
        artifact = self.build_progress_artifact(
            f"Technical Analysis: Data fetched for {resolved_ticker}",
            preview,
        )

        return TechnicalNodeResult(
            update=build_data_fetch_success_update(
                price_artifact_id=price_artifact_id,
                resolved_ticker=resolved_ticker,
                artifact=artifact,
            ),
            goto="fracdiff_compute",
        )

    async def run_fracdiff_compute(
        self,
        state: Mapping[str, object],
        *,
        calculate_rolling_fracdiff_fn: Callable[
            ..., tuple[object, object, int, object, object]
        ],
        compute_z_score_fn: Callable[..., object],
        calculate_rolling_z_score_fn: Callable[..., object],
        calculate_fd_bollinger_fn: Callable[..., JSONObject],
        calculate_statistical_strength_fn: Callable[..., JSONObject],
        calculate_fd_macd_fn: Callable[..., JSONObject],
        calculate_fd_obv_fn: Callable[..., JSONObject],
    ) -> TechnicalNodeResult:
        log_event(
            logger,
            event="technical_fracdiff_started",
            message="technical fracdiff computation started",
        )

        technical_context = technical_state_from_state(state)
        price_artifact_id = technical_context.price_artifact_id
        if price_artifact_id is None:
            log_event(
                logger,
                event="technical_fracdiff_missing_price_artifact_id",
                message="technical fracdiff failed due to missing price artifact id",
                level=logging.ERROR,
                error_code="TECHNICAL_PRICE_ARTIFACT_ID_MISSING",
            )
            return TechnicalNodeResult(
                update=build_fracdiff_error_update("Missing price artifact ID"),
                goto="END",
            )

        try:
            price_data = await self.port.load_price_series(price_artifact_id)
            if price_data is None:
                log_event(
                    logger,
                    event="technical_fracdiff_price_artifact_not_found",
                    message="technical fracdiff failed due to missing price artifact",
                    level=logging.ERROR,
                    error_code="TECHNICAL_PRICE_ARTIFACT_NOT_FOUND",
                    fields={"price_artifact_id": price_artifact_id},
                )
                return TechnicalNodeResult(
                    update=build_fracdiff_error_update(
                        "Price artifact not found in store"
                    ),
                    goto="END",
                )

            prices = pd.Series(price_data.price_series)
            prices.index = pd.to_datetime(prices.index)
            volumes = pd.Series(price_data.volume_series)
            volumes.index = pd.to_datetime(volumes.index)

            fd_series, optimal_d, window_length, adf_stat, adf_pvalue = (
                calculate_rolling_fracdiff_fn(
                    prices, lookback_window=252, recalc_step=5
                )
            )

            z_score = compute_z_score_fn(fd_series, lookback=252)
            z_score_series = calculate_rolling_z_score_fn(fd_series, lookback=252)

            bollinger_data = calculate_fd_bollinger_fn(fd_series)
            stat_strength_data = calculate_statistical_strength_fn(z_score_series)
            macd_data = calculate_fd_macd_fn(fd_series)
            obv_data = calculate_fd_obv_fn(prices, volumes)

            serialization = serialize_fracdiff_outputs(
                fd_series=fd_series,
                z_score_series=z_score_series,
                bollinger_data=bollinger_data,
                stat_strength_data=stat_strength_data,
                obv_data=obv_data,
            )

            chart_data = {
                "fracdiff_series": serialization.fracdiff_series,
                "z_score_series": serialization.z_score_series,
                "indicators": {
                    "bollinger": serialization.bollinger.to_dict(),
                    "obv": serialization.obv.to_dict(),
                },
            }

            key_prefix = state.get("ticker")
            chart_data_id = await self.port.save_chart_data(
                data=chart_data,
                produced_by="technical_analysis.fracdiff_compute",
                key_prefix=key_prefix if isinstance(key_prefix, str) else None,
            )
        except Exception as exc:
            log_event(
                logger,
                event="technical_fracdiff_failed",
                message="technical fracdiff computation failed",
                level=logging.ERROR,
                error_code="TECHNICAL_FRACDIFF_FAILED",
                fields={"exception": str(exc)},
            )
            return TechnicalNodeResult(
                update=build_fracdiff_error_update(f"Computation crashed: {str(exc)}"),
                goto="END",
            )

        ticker_value = resolved_ticker_from_state(state) or "N/A"
        preview = build_fracdiff_progress_preview(
            ticker=ticker_value,
            latest_price=prices.iloc[-1],
            z_score=z_score,
            optimal_d=optimal_d,
            statistical_strength=serialization.stat_strength.value,
        )
        artifact = self.build_progress_artifact(
            f"Technical Analysis: Patterns computed for {ticker_value}",
            preview,
        )

        return TechnicalNodeResult(
            update=build_fracdiff_success_update(
                latest_price=safe_float(prices.iloc[-1]),
                optimal_d=safe_float(optimal_d),
                z_score_latest=safe_float(z_score),
                chart_data_id=chart_data_id,
                window_length=int(window_length),
                adf_statistic=safe_float(adf_stat),
                adf_pvalue=safe_float(adf_pvalue),
                bollinger=serialization.bollinger.to_dict(),
                statistical_strength_val=serialization.stat_strength.value,
                macd=macd_data,
                obv=serialization.obv.to_dict(),
                artifact=artifact,
            ),
            goto="semantic_translate",
        )

    async def run_semantic_translate(
        self,
        state: Mapping[str, object],
        *,
        assemble_fn: Callable[[SemanticTagPolicyInput], SemanticTagPolicyResult],
        build_full_report_payload_fn: Callable[..., JSONObject],
        generate_interpretation_fn: Callable[..., Awaitable[str]],
        calculate_statistical_strength_fn: Callable[..., JSONObject],
        calculate_fd_bollinger_fn: Callable[..., JSONObject],
        calculate_fd_obv_fn: Callable[..., JSONObject],
        fetch_risk_free_series_fn: Callable[..., pd.Series],
        backtester_factory: type[object],
        format_backtest_for_llm_fn: Callable[[object], str],
        wfa_optimizer_factory: type[object],
        format_wfa_for_llm_fn: Callable[[object], str],
    ) -> TechnicalNodeResult:
        log_event(
            logger,
            event="technical_semantic_translate_started",
            message="technical semantic translation started",
        )

        ctx_raw = state.get("technical_analysis", {})
        ctx = ctx_raw if isinstance(ctx_raw, Mapping) else {}
        ticker = resolved_ticker_from_state(state)
        if ticker is None:
            log_event(
                logger,
                event="technical_semantic_translate_missing_ticker",
                message="technical semantic translation failed due to missing ticker",
                level=logging.ERROR,
                error_code="TECHNICAL_SEMANTIC_TICKER_MISSING",
            )
            error_update = build_semantic_error_update(
                "Missing intent_extraction.resolved_ticker"
            )
            return TechnicalNodeResult(update=error_update.update, goto="END")

        technical_context = technical_state_from_state(state)
        optimal_d = technical_context.optimal_d
        z_score = technical_context.z_score_latest
        if optimal_d is None or z_score is None:
            log_event(
                logger,
                event="technical_semantic_translate_missing_metrics",
                message="technical semantic translation failed due to missing fracdiff metrics",
                level=logging.ERROR,
                error_code="TECHNICAL_SEMANTIC_METRICS_MISSING",
            )
            error_update = build_semantic_error_update(
                "No FracDiff metrics available for translation"
            )
            return TechnicalNodeResult(update=error_update.update, goto="END")

        try:
            price_artifact_id = technical_context.price_artifact_id
            chart_artifact_id = technical_context.chart_data_id
            pipeline_result = await execute_semantic_pipeline(
                ticker=ticker,
                technical_context=dict(ctx),
                assemble_fn=assemble_fn,
                generate_interpretation_fn=generate_interpretation_fn,
                calculate_statistical_strength_fn=calculate_statistical_strength_fn,
                calculate_fd_bollinger_fn=calculate_fd_bollinger_fn,
                calculate_fd_obv_fn=calculate_fd_obv_fn,
                fetch_risk_free_series_fn=fetch_risk_free_series_fn,
                backtester_factory=backtester_factory,
                format_backtest_for_llm_fn=format_backtest_for_llm_fn,
                wfa_optimizer_factory=wfa_optimizer_factory,
                format_wfa_for_llm_fn=format_wfa_for_llm_fn,
                technical_port=self.port,
                price_artifact_id=price_artifact_id,
                chart_artifact_id=chart_artifact_id,
                build_full_report_payload_fn=build_full_report_payload_fn,
            )
            ta_update = await build_semantic_report_update(
                technical_port=self.port,
                ticker=ticker,
                technical_context=dict(ctx),
                summarize_preview=self.summarize_preview,
                pipeline_result=pipeline_result,
                build_output_artifact=self.build_semantic_output_artifact,
            )
            success_update = build_semantic_success_update(ta_update)
            success_update.update["messages"] = [
                AIMessage(
                    content="",
                    additional_kwargs={
                        "type": "technical_analysis",
                        "agent_id": "technical_analysis",
                        "status": "done",
                    },
                )
            ]
            log_event(
                logger,
                event="technical_semantic_translate_completed",
                message="technical semantic translation completed",
                fields={"ticker": ticker},
            )
            return TechnicalNodeResult(update=success_update.update, goto="END")
        except Exception as exc:
            log_event(
                logger,
                event="technical_semantic_translate_failed",
                message="technical semantic translation failed",
                level=logging.ERROR,
                error_code="TECHNICAL_SEMANTIC_TRANSLATION_FAILED",
                fields={"ticker": ticker, "exception": str(exc)},
            )
            error_update = build_semantic_error_update(
                f"Semantic translation failed: {str(exc)}"
            )
            return TechnicalNodeResult(update=error_update.update, goto="END")
