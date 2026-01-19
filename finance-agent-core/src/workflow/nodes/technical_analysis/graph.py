"""
Technical Analysis Sub-graph implementation.
Handles the flow: Data Fetch -> FracDiff Compute -> Semantic Translate.
"""

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from src.utils.logger import get_logger

from .semantic_layer import generate_interpretation, translate_to_tags
from .structures import FracDiffMetrics, SignalState, TechnicalSignal
from .subgraph_state import TechnicalAnalysisSubgraphState
from .tools import (
    apply_fracdiff,
    compute_z_score,
    fetch_daily_ohlcv,
    find_optimal_d,
    get_timestamp,
)

logger = get_logger(__name__)


# --- Nodes ---


def data_fetch_node(state: TechnicalAnalysisSubgraphState) -> Command:
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

    # Store raw data in state
    return Command(
        update={
            "technical_analysis": {
                "output": {
                    "ticker": resolved_ticker,
                    "raw_data": {
                        "price_series": df["price"]
                        .rename(index=lambda x: x.strftime("%Y-%m-%d"))
                        .map(float)
                        .to_dict()
                    },
                }
            },
            "current_node": "data_fetch",
            "internal_progress": {
                "data_fetch": "done",
                "fracdiff_compute": "running",
            },
        },
        goto="fracdiff_compute",
    )


def fracdiff_compute_node(state: TechnicalAnalysisSubgraphState) -> Command:
    """
    [Node 2] Compute optimal d and apply FracDiff transformation.
    """
    logger.info("--- TA: Computing FracDiff ---")

    # Extract price series from state
    output = state.technical_analysis.output
    if not output or "raw_data" not in output:
        logger.error("--- TA: No raw data available for FracDiff computation ---")
        return Command(
            update={
                "current_node": "fracdiff_compute",
                "internal_progress": {"fracdiff_compute": "error"},
            },
            goto=END,
        )

    import pandas as pd

    price_dict = output["raw_data"]["price_series"]
    prices = pd.Series(price_dict)
    prices.index = pd.to_datetime(prices.index)

    # Find optimal d value
    optimal_d, window_length, adf_stat, adf_pvalue = find_optimal_d(prices)

    # Apply FracDiff
    fd_series = apply_fracdiff(prices, optimal_d)

    # Compute Z-score
    z_score = compute_z_score(fd_series, lookback=252)

    # Update state with FracDiff metrics
    return Command(
        update={
            "technical_analysis": {
                "output": {
                    "ticker": output["ticker"],
                    "fracdiff_metrics": {
                        "optimal_d": float(optimal_d),
                        "window_length": int(window_length),
                        "adf_statistic": float(adf_stat),
                        "adf_pvalue": float(adf_pvalue),
                        "z_score": float(z_score),
                    },
                    "raw_data": {
                        **output["raw_data"],
                        "fracdiff_series": fd_series.rename(
                            index=lambda x: x.strftime("%Y-%m-%d")
                        )
                        .map(float)
                        .to_dict(),
                    },
                }
            },
            "current_node": "fracdiff_compute",
            "internal_progress": {
                "fracdiff_compute": "done",
                "semantic_translate": "running",
            },
        },
        goto="semantic_translate",
    )


async def semantic_translate_node(state: TechnicalAnalysisSubgraphState) -> Command:
    """
    [Node 3] Generate semantic tags and LLM interpretation.
    """
    logger.info("--- TA: Generating semantic interpretation ---")

    output = state.technical_analysis.output
    if not output or "fracdiff_metrics" not in output:
        logger.error("--- TA: No FracDiff metrics available for translation ---")
        return Command(
            update={
                "current_node": "semantic_translate",
                "internal_progress": {"semantic_translate": "error"},
            },
            goto=END,
        )

    ticker = output["ticker"]
    metrics = output["fracdiff_metrics"]
    optimal_d = metrics["optimal_d"]
    z_score = metrics["z_score"]

    # Generate deterministic tags
    tags_dict = translate_to_tags(z_score, optimal_d)

    # Generate LLM interpretation
    llm_interpretation = await generate_interpretation(tags_dict, ticker)

    # Build final TechnicalSignal structure
    frac_diff_metrics = FracDiffMetrics(
        optimal_d=optimal_d,
        window_length=metrics["window_length"],
        adf_statistic=metrics["adf_statistic"],
        adf_pvalue=metrics["adf_pvalue"],
        memory_strength=tags_dict["memory_strength"],
    )

    signal_state = SignalState(
        z_score=z_score,
        statistical_state=tags_dict["statistical_state"],
        direction=tags_dict["direction"],
        risk_level=tags_dict["risk_level"],
    )

    technical_signal = TechnicalSignal(
        ticker=ticker,
        timestamp=get_timestamp(),
        frac_diff_metrics=frac_diff_metrics,
        signal_state=signal_state,
        semantic_tags=tags_dict["tags"],
        llm_interpretation=llm_interpretation,
        raw_data=output.get("raw_data", {}),
    )

    # Create AI message for frontend
    message = AIMessage(
        content="",
        additional_kwargs={
            "type": "technical_analysis",
            "data": technical_signal.model_dump(),
            "agent_id": "technical_analysis",
        },
    )

    return Command(
        update={
            "technical_analysis": {"output": technical_signal.model_dump()},
            "current_node": "semantic_translate",
            "internal_progress": {"semantic_translate": "done"},
            "messages": [message],
        },
        goto=END,
    )


# Helper for initialization
technical_analysis_subgraph = None


async def get_technical_analysis_subgraph():
    """Lazy-initialize and return the technical_analysis subgraph."""
    global technical_analysis_subgraph
    if technical_analysis_subgraph is None:
        # Build Subgraph
        builder = StateGraph(TechnicalAnalysisSubgraphState)
        builder.add_node("data_fetch", data_fetch_node)
        builder.add_node("fracdiff_compute", fracdiff_compute_node)
        builder.add_node("semantic_translate", semantic_translate_node)

        builder.add_edge(START, "data_fetch")
        builder.add_edge("data_fetch", "fracdiff_compute")
        builder.add_edge("fracdiff_compute", "semantic_translate")

        # Compile (no checkpointer - inherited from parent)
        technical_analysis_subgraph = builder.compile()

    return technical_analysis_subgraph
