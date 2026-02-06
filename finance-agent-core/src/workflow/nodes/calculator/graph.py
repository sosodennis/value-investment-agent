"""
Calculator Sub-graph implementation.
"""

from langgraph.graph import END, START, StateGraph

from .nodes import calculation_node
from .subgraph_state import (
    CalculatorInput,
    CalculatorOutput,
    CalculatorState,
)


def build_calculator_subgraph():
    """純函數：構建並編譯子圖"""
    builder = StateGraph(
        CalculatorState,
        input=CalculatorInput,
        output=CalculatorOutput,
    )
    builder.add_node(
        "calculator",
        calculation_node,
        metadata={"agent_id": "calculator"},
    )
    builder.add_edge(START, "calculator")
    builder.add_edge("calculator", END)

    return builder.compile()
