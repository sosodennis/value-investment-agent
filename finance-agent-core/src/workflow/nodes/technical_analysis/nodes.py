import math
import time

import pandas as pd
from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.types import Command

from src.common.tools.logger import get_logger
from src.interface.schemas import AgentOutputArtifact, ArtifactReference
from src.services.artifact_manager import artifact_manager

from .backtester import (
    CombinedBacktester,
    WalkForwardOptimizer,
    format_backtest_for_llm,
    format_wfa_for_llm,
)
from .mappers import summarize_ta_for_preview
from .semantic_layer import assembler, generate_interpretation
from .subgraph_state import (
    TechnicalAnalysisState,
)
from .tools import (
    calculate_fd_bollinger,
    calculate_fd_macd,
    calculate_fd_obv,
    calculate_rolling_fracdiff,
    calculate_rolling_z_score,
    calculate_statistical_strength,
    compute_z_score,
    fetch_daily_ohlcv,
    fetch_risk_free_series,
)

logger = get_logger(__name__)


async def data_fetch_node(state: TechnicalAnalysisState) -> Command:
    """
    [Node 1] Fetch historical daily OHLCV data via yfinance.
    """
    intent_ctx = state.get("intent_extraction", {})
    resolved_ticker = intent_ctx.get("resolved_ticker") or state.get("ticker")
    if not resolved_ticker:
        logger.error("--- TA: No resolved ticker available, cannot proceed ---")
        return Command(
            update={
                "current_node": "data_fetch",
                "internal_progress": {"data_fetch": "error"},
                "node_statuses": {"technical_analysis": "error"},
                "error_logs": [
                    {
                        "node": "data_fetch",
                        "error": "No resolved ticker available",
                        "severity": "error",
                    }
                ],
            },
            goto=END,
        )

    logger.info(f"--- TA: Fetching data for {resolved_ticker} ---")

    try:
        # Fetch daily data (5 years for sufficient FracDiff window)
        df = fetch_daily_ohlcv(resolved_ticker, period="5y")
    except Exception as e:
        logger.error(f"--- TA: Data fetch failed for {resolved_ticker}: {e} ---")
        return Command(
            update={
                "current_node": "data_fetch",
                "internal_progress": {"data_fetch": "error"},
                "node_statuses": {"technical_analysis": "error"},
                "error_logs": [
                    {
                        "node": "data_fetch",
                        "error": f"Data fetch failed: {str(e)}",
                        "severity": "error",
                    }
                ],
            },
            goto=END,
        )

    if df is None or df.empty:
        logger.warning(f"⚠️  Could not fetch data for {resolved_ticker}")
        return Command(
            update={
                "current_node": "data_fetch",
                "internal_progress": {"data_fetch": "error"},
                "node_statuses": {"technical_analysis": "error"},
                "error_logs": [
                    {
                        "node": "data_fetch",
                        "error": "Empty data returned from provider",
                        "severity": "error",
                    }
                ],
            },
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

    price_artifact_id = await artifact_manager.save_artifact(
        data=price_data, artifact_type="price_series", key_prefix=resolved_ticker
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
    artifact = AgentOutputArtifact(
        summary=f"Technical Analysis: Data fetched for {resolved_ticker}",
        preview=preview,
        reference=None,
    )

    return Command(
        update={
            "technical_analysis": {
                "price_artifact_id": price_artifact_id,
                "ticker": resolved_ticker,
                "artifact": artifact,
            },
            "current_node": "data_fetch",
            "internal_progress": {
                "data_fetch": "done",
                "fracdiff_compute": "running",
            },
            "node_statuses": {"technical_analysis": "running"},
        },
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
            update={
                "current_node": "fracdiff_compute",
                "internal_progress": {"fracdiff_compute": "error"},
                "node_statuses": {"technical_analysis": "error"},
                "error_logs": [
                    {
                        "node": "fracdiff_compute",
                        "error": "Missing price artifact ID",
                        "severity": "error",
                    }
                ],
            },
            goto=END,
        )

    try:
        price_artifact = await artifact_manager.get_artifact(price_artifact_id)
        if not price_artifact:
            logger.error(f"--- TA: Price artifact {price_artifact_id} not found ---")
            return Command(
                update={
                    "current_node": "fracdiff_compute",
                    "internal_progress": {"fracdiff_compute": "error"},
                    "node_statuses": {"technical_analysis": "error"},
                    "error_logs": [
                        {
                            "node": "fracdiff_compute",
                            "error": "Price artifact not found in store",
                            "severity": "error",
                        }
                    ],
                },
                goto=END,
            )

        price_dict = price_artifact.data.get("price_series")
        volume_dict = price_artifact.data.get("volume_series")

        prices = pd.Series(price_dict)
        prices.index = pd.to_datetime(prices.index)

        volumes = pd.Series(volume_dict)
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

        def safe_float(val):
            try:
                f_val = float(val)
                if math.isnan(f_val):
                    return None
                return f_val
            except (ValueError, TypeError):
                return None

        bollinger_serializable = {
            "upper": safe_float(bollinger_data["upper"]),
            "middle": safe_float(bollinger_data["middle"]),
            "lower": safe_float(bollinger_data["lower"]),
            "state": bollinger_data["state"],
            "bandwidth": safe_float(bollinger_data["bandwidth"]),
        }

        stat_strength_serializable = {
            "value": safe_float(stat_strength_data["value"]),
        }

        obv_serializable = {
            "raw_obv_val": safe_float(obv_data["raw_obv_val"]),
            "fd_obv_z": safe_float(obv_data["fd_obv_z"]),
            "optimal_d": safe_float(obv_data["optimal_d"]),
            "state": obv_data["state"],
        }

        fd_dict = {
            k.strftime("%Y-%m-%d") if hasattr(k, "strftime") else k: safe_float(v)
            for k, v in fd_series.to_dict().items()
        }
        z_dict = {
            k.strftime("%Y-%m-%d") if hasattr(k, "strftime") else k: safe_float(v)
            for k, v in z_score_series.to_dict().items()
        }

        chart_data = {
            "fracdiff_series": fd_dict,
            "z_score_series": z_dict,
            "indicators": {
                "bollinger": bollinger_serializable,
                "obv": obv_serializable,
            },
        }

        chart_data_id = await artifact_manager.save_artifact(
            data=chart_data,
            artifact_type="ta_chart_data",
            key_prefix=state.get("ticker"),
        )
    except Exception as e:
        logger.error(f"--- TA: FracDiff computation crash: {e} ---", exc_info=True)
        return Command(
            update={
                "current_node": "fracdiff_compute",
                "internal_progress": {"fracdiff_compute": "error"},
                "node_statuses": {"technical_analysis": "error"},
                "error_logs": [
                    {
                        "node": "fracdiff_compute",
                        "error": f"Computation crashed: {str(e)}",
                        "severity": "error",
                    }
                ],
            },
            goto=END,
        )

    preview = {
        "ticker": state.get("ticker", "N/A"),
        "latest_price_display": f"${float(prices.iloc[-1]):,.2f}",
        "signal_display": "🧬 COMPUTING...",
        "z_score_display": f"Z: {float(z_score):+.2f}",
        "optimal_d_display": f"d={float(optimal_d):.2f}",
        "strength_display": f"Strength: {float(stat_strength_data['value']):.1f}",
    }
    artifact = AgentOutputArtifact(
        summary=f"Technical Analysis: Patterns computed for {state.get('ticker')}",
        preview=preview,
        reference=None,
    )

    return Command(
        update={
            "technical_analysis": {
                "latest_price": safe_float(prices.iloc[-1]),
                "optimal_d": safe_float(optimal_d),
                "z_score_latest": safe_float(z_score),
                "chart_data_id": chart_data_id,
                "window_length": int(window_length),
                "adf_statistic": safe_float(adf_stat),
                "adf_pvalue": safe_float(adf_pvalue),
                "bollinger": bollinger_serializable,
                "statistical_strength_val": stat_strength_serializable["value"],
                "macd": macd_data,
                "obv": obv_serializable,
                "artifact": artifact,
            },
            "current_node": "fracdiff_compute",
            "internal_progress": {
                "fracdiff_compute": "done",
                "semantic_translate": "running",
            },
        },
        goto="semantic_translate",
    )


async def semantic_translate_node(state: TechnicalAnalysisState) -> Command:
    """
    [Node 3] Generate semantic tags and LLM interpretation.
    """
    logger.info("--- TA: Generating semantic interpretation ---")

    ctx = state.get("technical_analysis", {})
    intent_ctx = state.get("intent_extraction", {})
    ticker = intent_ctx.get("resolved_ticker") or state.get("ticker")

    optimal_d = ctx.get("optimal_d")
    z_score = ctx.get("z_score_latest")

    if optimal_d is None or z_score is None:
        logger.error("--- TA: No FracDiff metrics available for translation ---")
        return Command(
            update={
                "current_node": "semantic_translate",
                "internal_progress": {"semantic_translate": "error"},
                "node_statuses": {"technical_analysis": "error"},
                "error_logs": [
                    {
                        "node": "semantic_translate",
                        "error": "No FracDiff metrics available for translation",
                        "severity": "error",
                    }
                ],
            },
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

        try:
            price_artifact_id = ctx.get("price_artifact_id")
            chart_artifact_id = ctx.get("chart_data_id")

            price_artifact = await artifact_manager.get_artifact(price_artifact_id)
            chart_artifact = await artifact_manager.get_artifact(chart_artifact_id)

            if not price_artifact or not chart_artifact:
                raise ValueError("Artifacts not found")

            price_dict = price_artifact.data.get("price_series")
            prices = pd.Series(price_dict)
            prices.index = pd.to_datetime(prices.index)

            vol_dict = price_artifact.data.get("volume_series")
            volumes = pd.Series(vol_dict)
            volumes.index = pd.to_datetime(volumes.index)

            fd_dict = chart_artifact.data.get("fracdiff_series")
            fd_series = pd.Series(fd_dict)
            fd_series.index = pd.to_datetime(fd_series.index)

            z_score_series = pd.Series(chart_artifact.data.get("z_score_series"))
            z_score_series.index = pd.to_datetime(z_score_series.index)

            stat_strength_full = calculate_statistical_strength(z_score_series)
            bb_full = calculate_fd_bollinger(fd_series)
            obv_full = calculate_fd_obv(prices, volumes)

            rf_series = fetch_risk_free_series(period="5y")

            backtester = CombinedBacktester(
                price_series=prices,
                z_score_series=z_score_series,
                stat_strength_dict=stat_strength_full,
                obv_dict=obv_full,
                bollinger_dict=bb_full,
                rf_series=rf_series,
            )

            bt_results = backtester.run(transaction_cost=0.0005)
            backtest_context = format_backtest_for_llm(bt_results)

            try:
                wfa_optimizer = WalkForwardOptimizer(backtester)
                wfa_results = wfa_optimizer.run(train_window=252, test_window=63)
                wfa_context = format_wfa_for_llm(wfa_results)
            except Exception:
                wfa_context = ""

        except Exception as e:
            logger.warning(
                f"Backtesting failed: {e}. Proceeding without statistical verification."
            )
            backtest_context = ""
            wfa_context = ""

        llm_interpretation = await generate_interpretation(
            tags_dict, ticker, backtest_context, wfa_context
        )

        try:
            preview = summarize_ta_for_preview(ctx)
            direction = str(tags_dict["direction"]).upper()

            statistical_state = "EQUILIBRIUM"
            z_abs = abs(ctx.get("z_score_latest", 0))
            if z_abs >= 2.0:
                statistical_state = "STATISTICAL_ANOMALY"
            elif z_abs >= 1.0:
                statistical_state = "DEVIATING"

            memory_strength = "BALANCED"
            opt_d = ctx.get("optimal_d", 0.5)
            if opt_d < 0.3:
                memory_strength = "STRUCTURALLY_STABLE"
            elif opt_d > 0.6:
                memory_strength = "FRAGILE"

            raw_data = {}
            if chart_artifact_id:
                chart_artifact = await artifact_manager.get_artifact(chart_artifact_id)
                if chart_artifact:
                    raw_data = {
                        "price_series": price_dict if "price_dict" in locals() else {},
                        "fracdiff_series": chart_artifact.data.get("fracdiff_series"),
                        "z_score_series": chart_artifact.data.get("z_score_series"),
                    }

            from datetime import datetime

            full_report_data = {
                "kind": "success",
                "ticker": ticker,
                "timestamp": datetime.now().isoformat(),
                "frac_diff_metrics": {
                    "optimal_d": ctx.get("optimal_d"),
                    "window_length": ctx.get("window_length"),
                    "adf_statistic": ctx.get("adf_statistic"),
                    "adf_pvalue": ctx.get("adf_pvalue"),
                    "memory_strength": memory_strength,
                },
                "signal_state": {
                    "z_score": ctx.get("z_score_latest"),
                    "statistical_state": statistical_state,
                    "direction": direction,
                    "risk_level": tags_dict.get("risk_level", "MEDIUM").lower(),
                    "confluence": {
                        "bollinger_state": ctx.get("bollinger", {}).get(
                            "state", "INSIDE"
                        ),
                        "macd_momentum": ctx.get("macd", {}).get(
                            "momentum_state", "NEUTRAL"
                        ),
                        "obv_state": ctx.get("obv", {}).get("state", "NEUTRAL"),
                        "statistical_strength": ctx.get(
                            "statistical_strength_val", 50.0
                        ),
                    },
                },
                "semantic_tags": tags_dict.get("tags", []),
                "llm_interpretation": llm_interpretation,
                "raw_data": raw_data,
            }

            timestamp_int = int(time.time())
            report_id = await artifact_manager.save_artifact(
                data=full_report_data,
                artifact_type="ta_full_report",
                key_prefix=f"ta_{ticker}_{timestamp_int}",
            )

            reference = None
            if report_id:
                reference = ArtifactReference(
                    artifact_id=report_id,
                    download_url=f"/api/artifacts/{report_id}",
                    type="ta_full_report",
                )

            artifact = AgentOutputArtifact(
                summary=f"Technical Analysis: {direction} (d={opt_d:.2f})",
                preview=preview,
                reference=reference,
            )
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
        if artifact:
            ta_update["artifact"] = artifact

        return Command(
            update={
                "technical_analysis": ta_update,
                "current_node": "semantic_translate",
                "internal_progress": {"semantic_translate": "done"},
                "node_statuses": {"technical_analysis": "done"},
                "messages": [
                    AIMessage(
                        content="",
                        additional_kwargs={
                            "type": "technical_analysis",
                            "agent_id": "technical_analysis",
                            "status": "done",
                        },
                    )
                ],
            },
            goto=END,
        )

    except Exception as e:
        logger.error(f"--- TA: Semantic translation failed: {e} ---", exc_info=True)
        return Command(
            update={
                "current_node": "semantic_translate",
                "internal_progress": {"semantic_translate": "error"},
                "node_statuses": {"technical_analysis": "error"},
                "error_logs": [
                    {
                        "node": "semantic_translate",
                        "error": f"Semantic translation failed: {str(e)}",
                        "severity": "error",
                    }
                ],
            },
            goto=END,
        )
