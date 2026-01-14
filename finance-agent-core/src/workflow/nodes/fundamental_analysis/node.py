"""
Planner Node - Entity Resolution and Valuation Model Selection.

This node:
1. Resolves user queries to stock tickers using OpenBB
2. Retrieves company profiles
3. Selects appropriate valuation models based on GICS sectors
4. Supports Human-in-the-Loop for ambiguous cases
"""

from typing import TYPE_CHECKING

from src.utils.logger import get_logger

from . import graph
from .structures import ValuationModel

if TYPE_CHECKING:
    from ...state import AgentState

logger = get_logger(__name__)


def fundamental_analysis_node(state: "AgentState") -> dict:
    """
    Wrapper for the Fundamental Analysis Sub-graph.
    """
    try:
        logger.info("=== Fundamental Analysis Node (Sub-agent) Started ===")

        # 1. Prepare sub-graph input
        user_query = state.get("user_query")
        if not user_query and state.get("ticker"):
            user_query = f"Valuate {state['ticker']}"

        if not user_query:
            return {
                "fundamental": {
                    "analysis_output": {
                        "status": "clarification_needed",
                        "error": "No query provided",
                    }
                }
            }

        sub_graph_input = {
            "user_query": user_query,
            "messages": state.get("messages") or [],
            "fundamental": {"status": "extraction"},
        }

        # 2. Invoke Sub-graph
        result = graph.fundamental_analysis_subgraph.invoke(sub_graph_input)

        # 3. Handle result
        fundamental_result = result.get("fundamental", {})
        status = fundamental_result.get("status")

        if status == "waiting_for_human":
            logger.warning("Fundamental analysis needs clarification")
            return {
                "fundamental": {
                    "analysis_output": {
                        "status": "clarification_needed",
                        "candidates": fundamental_result.get("ticker_candidates"),
                        "intent": fundamental_result.get("extracted_intent"),
                    }
                }
            }

        output = fundamental_result.get("analysis_output")
        if not output:
            return {
                "fundamental": {
                    "analysis_output": {
                        "status": "clarification_needed",
                        "error": "Fundamental analysis failed to produce output",
                    }
                }
            }

        # Map model_type for calculation node compatibility
        model_type_map = {
            ValuationModel.DCF_GROWTH: "saas",
            ValuationModel.DCF_STANDARD: "saas",
            ValuationModel.DDM: "bank",
            ValuationModel.FFO: "saas",
            ValuationModel.EV_REVENUE: "saas",
            ValuationModel.EV_EBITDA: "saas",
        }

        selected_model_val = output.get("model_type")
        # Finding the Enum member by value
        model_enum = next(
            (m for m in ValuationModel if m.value == selected_model_val),
            ValuationModel.DCF_STANDARD,
        )
        model_type = model_type_map.get(model_enum, "saas")

        return {
            "ticker": output["ticker"],
            "model_type": model_type,
            "fundamental": {"analysis_output": output},
        }
    except Exception as e:
        logger.error(f"Fundamental analysis failed: {e}")
        return {
            "fundamental": {
                "analysis_output": {
                    "status": "clarification_needed",
                    "error": str(e),
                }
            }
        }
