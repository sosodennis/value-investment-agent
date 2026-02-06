"""
Auditor Sub-graph implementation.
"""

from langgraph.graph import END, START, StateGraph

from .nodes import auditor_node
from .subgraph_state import (
    AuditorInput,
    AuditorOutput,
    AuditorState,
)


def build_auditor_subgraph():
    """純函數：構建並編譯子圖"""
    builder = StateGraph(
        AuditorState,
        input=AuditorInput,
        output=AuditorOutput,
    )
    builder.add_node(
        "auditor",
        auditor_node,
        metadata={"agent_id": "auditor"},
    )
    builder.add_edge(START, "auditor")
    builder.add_edge("auditor", END)

    return builder.compile()
