"""
Executor Sub-graph implementation.
"""

from langgraph.graph import END, START, StateGraph

from .nodes import executor_node
from .subgraph_state import (
    ExecutorInput,
    ExecutorOutput,
    ExecutorState,
)


def build_executor_subgraph():
    """純函數：構建並編譯子圖"""
    builder = StateGraph(
        ExecutorState,
        input=ExecutorInput,
        output=ExecutorOutput,
    )
    builder.add_node(
        "executor",
        executor_node,
        metadata={"agent_id": "executor"},
    )
    builder.add_edge(START, "executor")
    builder.add_edge("executor", END)

    return builder.compile()
