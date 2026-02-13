from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import pandas as pd

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
from src.agents.technical.application.view_models import build_fracdiff_preview
from src.agents.technical.data.mappers import serialize_fracdiff_outputs
from src.agents.technical.data.ports import (
    TechnicalArtifactPort,
    technical_artifact_port,
)
from src.agents.technical.domain.models import (
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)
from src.agents.technical.domain.services import safe_float
from src.agents.technical.interface.mappers import summarize_ta_for_preview
from src.common.contracts import (
    OUTPUT_KIND_TECHNICAL_ANALYSIS,
)
from src.common.tools.logger import get_logger
from src.common.types import JSONObject
from src.interface.schemas import build_artifact_payload

logger = get_logger(__name__)


@dataclass(frozen=True)
class TechnicalNodeResult:
    update: dict[str, object]
    goto: str


@dataclass(frozen=True)
class TechnicalOrchestrator:
    port: TechnicalArtifactPort
    summarize_preview: Callable[[JSONObject], JSONObject]

    async def run_data_fetch(
        self,
        state: Mapping[str, object],
        *,
        fetch_daily_ohlcv_fn: Callable[[str], pd.DataFrame],
    ) -> TechnicalNodeResult:
        resolved_ticker = resolved_ticker_from_state(state)
        if resolved_ticker is None:
            logger.error("--- TA: No resolved ticker available, cannot proceed ---")
            return TechnicalNodeResult(
                update=build_data_fetch_error_update("No resolved ticker available"),
                goto="END",
            )

        logger.info(f"--- TA: Fetching data for {resolved_ticker} ---")

        try:
            df = fetch_daily_ohlcv_fn(resolved_ticker)
        except Exception as exc:
            logger.error(f"--- TA: Data fetch failed for {resolved_ticker}: {exc} ---")
            return TechnicalNodeResult(
                update=build_data_fetch_error_update(f"Data fetch failed: {str(exc)}"),
                goto="END",
            )

        if df is None or df.empty:
            logger.warning(f"⚠️  Could not fetch data for {resolved_ticker}")
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

        preview = {
            "ticker": resolved_ticker,
            "latest_price_display": f"${df['price'].iloc[-1]:,.2f}",
            "signal_display": "📊 FETCHING DATA...",
            "z_score_display": "Z: N/A",
            "optimal_d_display": "d=N/A",
            "strength_display": "Strength: N/A",
        }
        artifact = build_artifact_payload(
            kind=OUTPUT_KIND_TECHNICAL_ANALYSIS,
            summary=f"Technical Analysis: Data fetched for {resolved_ticker}",
            preview=preview,
            reference=None,
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
        logger.info("--- TA: Computing Rolling FracDiff ---")

        technical_context = technical_state_from_state(state)
        price_artifact_id = technical_context.price_artifact_id
        if price_artifact_id is None:
            logger.error(
                "--- TA: No price artifact ID available for FracDiff computation ---"
            )
            return TechnicalNodeResult(
                update=build_fracdiff_error_update("Missing price artifact ID"),
                goto="END",
            )

        try:
            price_data = await self.port.load_price_series(price_artifact_id)
            if price_data is None:
                logger.error(
                    f"--- TA: Price artifact {price_artifact_id} not found ---"
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
                    "bollinger": serialization.bollinger,
                    "obv": serialization.obv,
                },
            }

            key_prefix = state.get("ticker")
            chart_data_id = await self.port.save_chart_data(
                data=chart_data,
                produced_by="technical_analysis.fracdiff_compute",
                key_prefix=key_prefix if isinstance(key_prefix, str) else None,
            )
        except Exception as exc:
            logger.error(
                f"--- TA: FracDiff computation crash: {exc} ---", exc_info=True
            )
            return TechnicalNodeResult(
                update=build_fracdiff_error_update(f"Computation crashed: {str(exc)}"),
                goto="END",
            )

        ticker_value = resolved_ticker_from_state(state) or "N/A"
        preview = build_fracdiff_preview(
            ticker=ticker_value,
            latest_price=prices.iloc[-1],
            z_score=z_score,
            optimal_d=optimal_d,
            statistical_strength=serialization.stat_strength.get("value"),
        )
        artifact = build_artifact_payload(
            kind=OUTPUT_KIND_TECHNICAL_ANALYSIS,
            summary=f"Technical Analysis: Patterns computed for {ticker_value}",
            preview=preview,
            reference=None,
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
                bollinger=serialization.bollinger,
                statistical_strength_val=serialization.stat_strength["value"],
                macd=macd_data,
                obv=serialization.obv,
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
        logger.info("--- TA: Generating semantic interpretation ---")

        ctx_raw = state.get("technical_analysis", {})
        ctx = ctx_raw if isinstance(ctx_raw, Mapping) else {}
        ticker = resolved_ticker_from_state(state)
        if ticker is None:
            logger.error("--- TA: Missing resolved ticker for semantic translation ---")
            error_update = build_semantic_error_update(
                "Missing intent_extraction.resolved_ticker"
            )
            return TechnicalNodeResult(update=error_update.update, goto="END")

        technical_context = technical_state_from_state(state)
        optimal_d = technical_context.optimal_d
        z_score = technical_context.z_score_latest
        if optimal_d is None or z_score is None:
            logger.error("--- TA: No FracDiff metrics available for translation ---")
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
            )
            success_update = build_semantic_success_update(ta_update)
            return TechnicalNodeResult(update=success_update.update, goto="END")
        except Exception as exc:
            logger.error(
                f"--- TA: Semantic translation failed: {exc} ---", exc_info=True
            )
            error_update = build_semantic_error_update(
                f"Semantic translation failed: {str(exc)}"
            )
            return TechnicalNodeResult(update=error_update.update, goto="END")


technical_orchestrator = TechnicalOrchestrator(
    port=technical_artifact_port,
    summarize_preview=summarize_ta_for_preview,
)
