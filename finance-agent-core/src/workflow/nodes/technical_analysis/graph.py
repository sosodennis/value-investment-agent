"""
Technical Analysis Sub-graph implementation.
Handles the flow: Data Fetch -> FracDiff Compute -> Semantic Translate.
"""

import pandas as pd
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from src.services.artifact_manager import artifact_manager
from src.utils.logger import get_logger

from .backtester import (
    CombinedBacktester,
    WalkForwardOptimizer,
    format_backtest_for_llm,
    format_wfa_for_llm,
)
from .semantic_layer import assembler, generate_interpretation
from .subgraph_state import (
    TechnicalAnalysisInput,
    TechnicalAnalysisOutput,
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


# --- Nodes ---


def data_fetch_node(state: TechnicalAnalysisState) -> Command:
    """
    [Node 1] Fetch historical daily OHLCV data via yfinance.
    """
    # Get resolved ticker from intent_extraction context
    resolved_ticker = state.intent_extraction.resolved_ticker or state.ticker
    if not resolved_ticker:
        logger.error("--- TA: No resolved ticker available, cannot proceed ---")
        return Command(
            update={
                "current_node": "data_fetch",
                "internal_progress": {"data_fetch": "error"},
            },
            goto=END,
        )

    logger.info(f"--- TA: Fetching data for {resolved_ticker} ---")

    # Fetch daily data (5 years for sufficient FracDiff window)
    df = fetch_daily_ohlcv(resolved_ticker, period="5y")

    if df is None or df.empty:
        logger.warning(f"⚠️  Could not fetch data for {resolved_ticker}")
        return Command(
            update={
                "current_node": "data_fetch",
                "internal_progress": {"data_fetch": "error"},
            },
            goto=END,
        )

    # [Refactor] Store raw data in Artifact Store instead of State
    price_data = {
        "price_series": df["price"]
        .rename(index=lambda x: x.strftime("%Y-%m-%d"))
        .map(float)
        .to_dict(),
        "volume_series": df["volume"]
        .rename(index=lambda x: x.strftime("%Y-%m-%d"))
        .map(float)
        .to_dict(),
    }

    price_artifact_id = await artifact_manager.save_artifact(
        data=price_data, artifact_type="price_series", key_prefix=resolved_ticker
    )

    return Command(
        update={
            "technical_analysis": {
                "price_artifact_id": price_artifact_id,
            },
            "current_node": "data_fetch",
            "internal_progress": {
                "data_fetch": "done",
                "fracdiff_compute": "running",
            },
        },
        goto="fracdiff_compute",
    )


async def fracdiff_compute_node(state: TechnicalAnalysisState) -> Command:
    """
    [Node 2] Compute optimal d and apply FracDiff transformation using ROLLING window.
    Eliminates look-ahead bias for enterprise-grade backtesting.
    """
    logger.info("--- TA: Computing Rolling FracDiff ---")

    # [Refactor] Extract price series from Artifact Store instead of State
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
            },
            goto=END,
        )

    price_artifact = await artifact_manager.get_artifact(price_artifact_id)
    if not price_artifact:
        logger.error(f"--- TA: Price artifact {price_artifact_id} not found ---")
        return Command(
            update={
                "current_node": "fracdiff_compute",
                "internal_progress": {"fracdiff_compute": "error"},
            },
            goto=END,
        )

    price_dict = price_artifact.data.get("price_series")
    volume_dict = price_artifact.data.get("volume_series")

    prices = pd.Series(price_dict)
    prices.index = pd.to_datetime(prices.index)

    volumes = pd.Series(volume_dict)
    volumes.index = pd.to_datetime(volumes.index)

    # [EVOLUTION] Use ROLLING FracDiff instead of static global d
    # This simulates a "Live" environment where we only know past data.
    # We use a 252-day (1 year) lookback window for the ADF test.
    fd_series, optimal_d, window_length, adf_stat, adf_pvalue = (
        calculate_rolling_fracdiff(prices, lookback_window=252, recalc_step=5)
    )

    # Compute Z-score (current value)
    z_score = compute_z_score(fd_series, lookback=252)

    # [CRITICAL FIX] Calculate rolling Z-score series for frontend chart
    # This ensures the chart data mathematically aligns with +/- 2.0 thresholds
    z_score_series = calculate_rolling_z_score(fd_series, lookback=252)

    # Calculate confluence indicators
    bollinger_data = calculate_fd_bollinger(fd_series)
    stat_strength_data = calculate_statistical_strength(
        z_score_series
    )  # [Change] Use CDF
    macd_data = calculate_fd_macd(fd_series)

    # Calculate FD-OBV (volume analysis)
    obv_data = calculate_fd_obv(prices, volumes)

    # [Fix] Remove pandas Series from indicators for msgpack serialization
    # Keep only scalar values for state storage
    bollinger_serializable = {
        "upper": bollinger_data["upper"],
        "middle": bollinger_data["middle"],
        "lower": bollinger_data["lower"],
        "state": bollinger_data["state"],
        "bandwidth": bollinger_data["bandwidth"],
    }

    stat_strength_serializable = {
        "value": stat_strength_data["value"],
        # Thresholds are irrelevant for CDF (fixed constants)
    }

    obv_serializable = {
        "raw_obv_val": obv_data["raw_obv_val"],
        "fd_obv_z": obv_data["fd_obv_z"],
        "optimal_d": obv_data["optimal_d"],
        "state": obv_data["state"],
    }

    # [Refactor] Store chart data in Artifact Store
    # Reformat indices to strings for JSON serialization
    fd_dict = {
        k.strftime("%Y-%m-%d") if hasattr(k, "strftime") else k: float(v)
        for k, v in fd_series.to_dict().items()
    }
    z_dict = {
        k.strftime("%Y-%m-%d") if hasattr(k, "strftime") else k: float(v)
        for k, v in z_score_series.to_dict().items()
    }

    chart_data = {
        "fracdiff_series": fd_dict,
        "z_score_series": z_dict,
        "indicators": {
            "bollinger": calculate_fd_bollinger(fd_series),
            "obv": calculate_fd_obv(prices, volumes),
        },
    }

    chart_data_id = await artifact_manager.save_artifact(
        data=chart_data,
        artifact_type="ta_chart_data",
        key_prefix=state.get("ticker"),
    )

    # Update state with FracDiff metrics and indicators in context
    return Command(
        update={
            "technical_analysis": {
                "latest_price": float(prices.iloc[-1]),
                "optimal_d": float(optimal_d),
                "z_score_latest": float(z_score),
                "chart_data_id": chart_data_id,
                "window_length": int(window_length),
                "adf_statistic": float(adf_stat),
                "adf_pvalue": float(adf_pvalue),
                "bollinger": bollinger_serializable,
                "statistical_strength_val": stat_strength_serializable["value"],
                "macd": macd_data,
                "obv": obv_serializable,
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
    ticker = state.intent_extraction.resolved_ticker or state.ticker

    optimal_d = ctx.get("optimal_d")
    z_score = ctx.get("z_score_latest")

    if optimal_d is None or z_score is None:
        logger.error("--- TA: No FracDiff metrics available for translation ---")
        return Command(
            update={
                "current_node": "semantic_translate",
                "internal_progress": {"semantic_translate": "error"},
            },
            goto=END,
        )

    # Use SemanticAssembler for multi-dimensional analysis
    tags_dict = assembler.assemble(
        z_score=z_score,
        optimal_d=optimal_d,
        bollinger_data=ctx.get("bollinger", {"state": "INSIDE"}),
        stat_strength_data={
            "value": ctx.get("statistical_strength_val", 50.0)
        },  # [Change] Use CDF
        macd_data=ctx.get("macd", {"momentum_state": "NEUTRAL"}),
        obv_data=ctx.get("obv", {"state": "NEUTRAL", "fd_obv_z": 0.0}),
    )

    # [NEW] Run Backtesting for Statistical Verification
    try:
        # Fetch from Artifact Store
        price_artifact_id = ctx.get("price_artifact_id")
        chart_artifact_id = ctx.get("chart_data_id")

        price_artifact = await artifact_manager.get_artifact(price_artifact_id)
        chart_artifact = await artifact_manager.get_artifact(chart_artifact_id)

        if not price_artifact or not chart_artifact:
            raise ValueError("Artifacts not found")

        # Price reconstruction
        price_dict = price_artifact.data.get("price_series")
        prices = pd.Series(price_dict)
        prices.index = pd.to_datetime(prices.index)

        vol_dict = price_artifact.data.get("volume_series")
        volumes = pd.Series(vol_dict)
        volumes.index = pd.to_datetime(volumes.index)

        # Chart data reconstruction
        fd_dict = chart_artifact.data.get("fracdiff_series")
        fd_series = pd.Series(fd_dict)
        fd_series.index = pd.to_datetime(fd_series.index)

        z_score_series = pd.Series(chart_artifact.data.get("z_score_series"))
        z_score_series.index = pd.to_datetime(z_score_series.index)

        # Full indicator reconstruction from chart artifact or recalculate
        stat_strength_full = calculate_statistical_strength(z_score_series)
        indicators_artifact = chart_artifact.data.get("indicators", {})
        bb_full = indicators_artifact.get("bollinger") or calculate_fd_bollinger(
            fd_series
        )
        obv_full = indicators_artifact.get("obv") or calculate_fd_obv(prices, volumes)

        # Fetch Risk-Free Rate
        rf_series = fetch_risk_free_series(period="5y")

        # Initialize backtester
        backtester = CombinedBacktester(
            price_series=prices,
            z_score_series=z_score_series,
            stat_strength_dict=stat_strength_full,
            obv_dict=obv_full,
            bollinger_dict=bb_full,
            rf_series=rf_series,
        )

        # Run backtest
        bt_results = backtester.run(transaction_cost=0.0005)
        backtest_context = format_backtest_for_llm(bt_results)

        # WFA
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

    # Generate LLM interpretation
    llm_interpretation = await generate_interpretation(
        tags_dict, ticker, backtest_context, wfa_context
    )

    # Note: We NO LONGER create AgentOutputArtifact here.
    # We update the context with final fields for the adapter to use.

    return Command(
        update={
            "technical_analysis": {
                "signal": tags_dict["direction"],
                "statistical_strength": tags_dict["statistical_state"],
                "risk_level": tags_dict["risk_level"],
                "llm_interpretation": llm_interpretation,
                "semantic_tags": tags_dict["tags"],
                "memory_strength": tags_dict["memory_strength"],
            },
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


def build_technical_subgraph():
    """Build and return the technical_analysis subgraph."""
    builder = StateGraph(
        TechnicalAnalysisState,
        input=TechnicalAnalysisInput,
        output=TechnicalAnalysisOutput,
    )
    builder.add_node(
        "data_fetch",
        RunnableLambda(data_fetch_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "technical_analysis"},
    )
    builder.add_node(
        "fracdiff_compute",
        RunnableLambda(fracdiff_compute_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "technical_analysis"},
    )
    builder.add_node(
        "semantic_translate",
        semantic_translate_node,
        metadata={"agent_id": "technical_analysis"},
    )

    builder.add_edge(START, "data_fetch")
    builder.add_edge("data_fetch", "fracdiff_compute")
    builder.add_edge("fracdiff_compute", "semantic_translate")

    return builder.compile()
