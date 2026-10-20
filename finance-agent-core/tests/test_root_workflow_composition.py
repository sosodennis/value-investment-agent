from __future__ import annotations

from collections.abc import Callable, Mapping

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.workflow.graph import RootAgentGraphs, build_root_graph
from src.workflow.state import AgentState


def _agent_graph(
    node_name: str,
    run: Callable[[AgentState], Mapping[str, object]],
) -> CompiledStateGraph:
    builder = StateGraph(AgentState)
    builder.add_node(node_name, run)
    builder.add_edge(START, node_name)
    builder.add_edge(node_name, END)
    return builder.compile()


def test_root_graph_hands_off_merged_research_to_debate() -> None:
    debate_inputs: list[Mapping[str, object]] = []

    def record_debate(state: AgentState) -> Mapping[str, object]:
        debate_inputs.append(state)
        return {"debate": {"final_verdict": "hold"}}

    graphs = RootAgentGraphs(
        intent=_agent_graph(
            "intent_fake",
            lambda _: {"intent_extraction": {"resolved_ticker": "AAPL"}},
        ),
        fundamental=_agent_graph(
            "fundamental_fake",
            lambda _: {
                "fundamental_analysis": {"financial_reports_artifact_id": "fa-1"}
            },
        ),
        news=_agent_graph(
            "news_fake",
            lambda _: {"financial_news_research": {"report_id": "news-1"}},
        ),
        technical=_agent_graph(
            "technical_fake",
            lambda _: {"technical_analysis": {"signal": "HOLD"}},
        ),
        debate=_agent_graph("debate_fake", record_debate),
    )

    graph = build_root_graph(graphs).compile()
    result = graph.invoke({"user_query": "Analyze Apple", "messages": []})

    assert set(graph.get_graph().nodes) == {
        "__start__",
        "intent_agent",
        "fundamental_agent",
        "news_agent",
        "technical_agent",
        "consolidate_research",
        "debate_agent",
        "__end__",
    }
    assert len(debate_inputs) == 1
    assert debate_inputs[0]["intent_extraction"]["resolved_ticker"] == "AAPL"
    assert (
        debate_inputs[0]["fundamental_analysis"]["financial_reports_artifact_id"]
        == "fa-1"
    )
    assert debate_inputs[0]["financial_news_research"]["report_id"] == "news-1"
    assert debate_inputs[0]["technical_analysis"]["signal"] == "HOLD"
    assert result["debate"]["final_verdict"] == "hold"
