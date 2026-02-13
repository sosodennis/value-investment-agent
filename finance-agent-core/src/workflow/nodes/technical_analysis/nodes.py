import time

import pandas as pd
from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.types import Command

from src.agents.technical.application.services import (
    assemble_backtest_context,
    assemble_semantic_finalize,
    build_data_fetch_error_update,
    build_data_fetch_success_update,
    build_fracdiff_error_update,
    build_fracdiff_preview,
    build_fracdiff_success_update,
    build_semantic_error_update,
    build_semantic_success_update,
    safe_float,
    serialize_fracdiff_outputs,
)
from src.agents.technical.data.ports import technical_artifact_port
from src.agents.technical.interface.mappers import summarize_ta_for_preview
from src.common.contracts import (
    ARTIFACT_KIND_TA_FULL_REPORT,
    OUTPUT_KIND_TECHNICAL_ANALYSIS,
)
from src.common.tools.logger import get_logger
from src.interface.canonical_serializers import canonicalize_technical_artifact_data
from src.interface.schemas import ArtifactReference, build_artifact_payload

from .subgraph_state import (
    TechnicalAnalysisState,
)
from .tools import (
    CombinedBacktester,
    WalkForwardOptimizer,
    assembler,
    calculate_fd_bollinger,
    calculate_fd_macd,
    calculate_fd_obv,
    calculate_rolling_fracdiff,
    calculate_rolling_z_score,
    calculate_statistical_strength,
    compute_z_score,
    fetch_daily_ohlcv,
    fetch_risk_free_series,
    format_backtest_for_llm,
    format_wfa_for_llm,
    generate_interpretation,
)

logger = get_logger(__name__)


async def data_fetch_node(state: TechnicalAnalysisState) -> Command:
    """
    [Node 1] Fetch historical daily OHLCV data via yfinance.
    """
    intent_ctx = state.get("intent_extraction", {})
    resolved_ticker = intent_ctx.get("resolved_ticker")
    if not resolved_ticker:
        logger.error("--- TA: No resolved ticker available, cannot proceed ---")
        return Command(
            update=build_data_fetch_error_update("No resolved ticker available"),
            goto=END,
        )

    logger.info(f"--- TA: Fetching data for {resolved_ticker} ---")

    try:
        # Fetch daily data (5 years for sufficient FracDiff window)
        df = fetch_daily_ohlcv(resolved_ticker, period="5y")
    except Exception as e:
        logger.error(f"--- TA: Data fetch failed for {resolved_ticker}: {e} ---")
        return Command(
            update=build_data_fetch_error_update(f"Data fetch failed: {str(e)}"),
            goto=END,
        )

    if df is None or df.empty:
        logger.warning(f"⚠️  Could not fetch data for {resolved_ticker}")
        return Command(
            update=build_data_fetch_error_update("Empty data returned from provider"),
            goto=END,
        )

    # [Refactor] Store raw data in Artifact Store instead of State
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

    price_artifact_id = await technical_artifact_port.save_price_series(
        data=price_data,
        produced_by="technical_analysis.data_fetch",
        key_prefix=resolved_ticker,
    )

    # [NEW] Emit preliminary artifact for real-time UI
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

    return Command(
        update=build_data_fetch_success_update(
            price_artifact_id=price_artifact_id,
            resolved_ticker=resolved_ticker,
            artifact=artifact,
        ),
        goto="fracdiff_compute",
    )


async def fracdiff_compute_node(state: TechnicalAnalysisState) -> Command:
    """
    [Node 2] Compute optimal d and apply FracDiff transformation using ROLLING window.
    """
    logger.info("--- TA: Computing Rolling FracDiff ---")

    price_ctx = state.get("technical_analysis", {})
    price_artifact_id = price_ctx.get("price_artifact_id")

    if not price_artifact_id:
        logger.error(
            "--- TA: No price artifact ID available for FracDiff computation ---"
        )
        return Command(
            update=build_fracdiff_error_update("Missing price artifact ID"),
            goto=END,
        )

    try:
        price_data = await technical_artifact_port.load_price_series(price_artifact_id)
        if price_data is None:
            logger.error(f"--- TA: Price artifact {price_artifact_id} not found ---")
            return Command(
                update=build_fracdiff_error_update("Price artifact not found in store"),
                goto=END,
            )

        prices = pd.Series(price_data.price_series)
        prices.index = pd.to_datetime(prices.index)

        volumes = pd.Series(price_data.volume_series)
        volumes.index = pd.to_datetime(volumes.index)

        fd_series, optimal_d, window_length, adf_stat, adf_pvalue = (
            calculate_rolling_fracdiff(prices, lookback_window=252, recalc_step=5)
        )

        z_score = compute_z_score(fd_series, lookback=252)
        z_score_series = calculate_rolling_z_score(fd_series, lookback=252)

        bollinger_data = calculate_fd_bollinger(fd_series)
        stat_strength_data = calculate_statistical_strength(z_score_series)
        macd_data = calculate_fd_macd(fd_series)
        obv_data = calculate_fd_obv(prices, volumes)

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

        chart_data_id = await technical_artifact_port.save_chart_data(
            data=chart_data,
            produced_by="technical_analysis.fracdiff_compute",
            key_prefix=state.get("ticker"),
        )
    except Exception as e:
        logger.error(f"--- TA: FracDiff computation crash: {e} ---", exc_info=True)
        return Command(
            update=build_fracdiff_error_update(f"Computation crashed: {str(e)}"),
            goto=END,
        )

    ticker_value = str(state.get("ticker", "N/A"))
    preview = build_fracdiff_preview(
        ticker=ticker_value,
        latest_price=prices.iloc[-1],
        z_score=z_score,
        optimal_d=optimal_d,
        statistical_strength=serialization.stat_strength.get("value"),
    )
    artifact = build_artifact_payload(
        kind=OUTPUT_KIND_TECHNICAL_ANALYSIS,
        summary=f"Technical Analysis: Patterns computed for {state.get('ticker')}",
        preview=preview,
        reference=None,
    )

    return Command(
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


async def semantic_translate_node(state: TechnicalAnalysisState) -> Command:
    """
    [Node 3] Generate semantic tags and LLM interpretation.
    """
    logger.info("--- TA: Generating semantic interpretation ---")

    ctx = state.get("technical_analysis", {})
    intent_ctx = state.get("intent_extraction", {})
    ticker = intent_ctx.get("resolved_ticker")

    if not ticker:
        logger.error("--- TA: Missing resolved ticker for semantic translation ---")
        error_update = build_semantic_error_update(
            "Missing intent_extraction.resolved_ticker"
        )
        return Command(
            update=error_update.update,
            goto=END,
        )

    optimal_d = ctx.get("optimal_d")
    z_score = ctx.get("z_score_latest")

    if optimal_d is None or z_score is None:
        logger.error("--- TA: No FracDiff metrics available for translation ---")
        error_update = build_semantic_error_update(
            "No FracDiff metrics available for translation"
        )
        return Command(
            update=error_update.update,
            goto=END,
        )

    try:
        tags_dict = assembler.assemble(
            z_score=z_score,
            optimal_d=optimal_d,
            bollinger_data=ctx.get("bollinger", {"state": "INSIDE"}),
            stat_strength_data={"value": ctx.get("statistical_strength_val", 50.0)},
            macd_data=ctx.get("macd", {"momentum_state": "NEUTRAL"}),
            obv_data=ctx.get("obv", {"state": "NEUTRAL", "fd_obv_z": 0.0}),
        )

        price_artifact_id = ctx.get("price_artifact_id")
        chart_artifact_id = ctx.get("chart_data_id")
        backtest_result = await assemble_backtest_context(
            technical_port=technical_artifact_port,
            price_artifact_id=price_artifact_id,
            chart_artifact_id=chart_artifact_id,
            calculate_statistical_strength_fn=calculate_statistical_strength,
            calculate_fd_bollinger_fn=calculate_fd_bollinger,
            calculate_fd_obv_fn=calculate_fd_obv,
            fetch_risk_free_series_fn=fetch_risk_free_series,
            backtester_factory=CombinedBacktester,
            format_backtest_for_llm_fn=format_backtest_for_llm,
            wfa_optimizer_factory=WalkForwardOptimizer,
            format_wfa_for_llm_fn=format_wfa_for_llm,
        )
        backtest_context = backtest_result.backtest_context
        wfa_context = backtest_result.wfa_context
        price_data = backtest_result.price_data
        chart_data = backtest_result.chart_data

        llm_interpretation = await generate_interpretation(
            tags_dict, ticker, backtest_context, wfa_context
        )

        try:
            preview = summarize_ta_for_preview(ctx)
            semantic_result = assemble_semantic_finalize(
                ticker=ticker,
                technical_context=ctx,
                tags_dict=tags_dict,
                llm_interpretation=llm_interpretation,
                price_data=price_data,
                chart_data=chart_data,
            )
            direction = semantic_result.direction
            opt_d = semantic_result.opt_d
            full_report_data = canonicalize_technical_artifact_data(
                semantic_result.full_report_data_raw
            )

            timestamp_int = int(time.time())
            report_id = await technical_artifact_port.save_full_report(
                data=full_report_data,
                produced_by="technical_analysis.semantic_translate",
                key_prefix=f"ta_{ticker}_{timestamp_int}",
            )

            reference = None
            if report_id:
                reference = ArtifactReference(
                    artifact_id=report_id,
                    download_url=f"/api/artifacts/{report_id}",
                    type=ARTIFACT_KIND_TA_FULL_REPORT,
                )

            artifact = build_artifact_payload(
                kind=OUTPUT_KIND_TECHNICAL_ANALYSIS,
                summary=f"Technical Analysis: {direction} (d={opt_d:.2f})",
                preview=preview,
                reference=reference,
            )
            ta_update = semantic_result.ta_update
            ta_update["artifact"] = artifact
        except Exception as e:
            logger.error(f"Failed to generate artifact in node: {e}")
            artifact = None
            ta_update = {
                "signal": tags_dict["direction"],
                "statistical_strength": tags_dict["statistical_state"],
                "risk_level": tags_dict["risk_level"],
                "llm_interpretation": llm_interpretation,
                "semantic_tags": tags_dict["tags"],
                "memory_strength": tags_dict["memory_strength"],
            }

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
        return Command(update=success_update.update, goto=END)

    except Exception as e:
        logger.error(f"--- TA: Semantic translation failed: {e} ---", exc_info=True)
        error_update = build_semantic_error_update(
            f"Semantic translation failed: {str(e)}"
        )
        return Command(update=error_update.update, goto=END)
