from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.shared.cross_agent.domain.market_identity import CompanyProfile
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


def _run_input(query: str) -> dict[str, object]:
    return {
        "user_query": query,
        "messages": [],
        "company_profile": None,
        "artifact_references": None,
        "workflow_activity_statuses": None,
        "active_activity_id": None,
        "workflow_activity_updates": None,
        "error_logs": None,
    }


def test_root_graph_imports_no_agent_internals_or_root_nodes() -> None:
    source = Path("src/workflow/graph.py").read_text()
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(
        module.startswith("src.workflow.nodes") for module in imported_modules
    )
    assert all(
        not module.startswith("src.agents.") or module.endswith(".entrypoint")
        for module in imported_modules
    )


def test_root_graph_merges_parallel_artifact_handoffs_and_resets_each_run() -> None:
    debate_inputs: list[Mapping[str, object]] = []

    def profile_for(state: AgentState) -> CompanyProfile:
        ticker = "AAPL" if state["user_query"] == "Analyze Apple" else "MSFT"
        return CompanyProfile(ticker=ticker, name=ticker)

    def return_profile(state: AgentState) -> Mapping[str, object]:
        return {"company_profile": profile_for(state)}

    def return_artifact(key: str) -> Callable[[AgentState], Mapping[str, object]]:
        def run(state: AgentState) -> Mapping[str, object]:
            ticker = profile_for(state).ticker.lower()
            return {
                "artifact_references": {
                    key: {
                        "artifact_id": f"{ticker}-{key}",
                        "download_url": f"/api/v1/artifacts/{ticker}-{key}",
                        "type": key,
                    }
                },
                "workflow_activity_statuses": {f"{key}-complete": "done"},
                "workflow_activity_updates": {f"{key}-complete": "done"},
                "error_logs": [{"node": key, "error": "diagnostic"}],
            }

        return run

    def record_debate(state: AgentState) -> Mapping[str, object]:
        debate_inputs.append(dict(state))
        return {}

    graphs = RootAgentGraphs(
        intent=_agent_graph("private_intent_node", return_profile),
        fundamental=_agent_graph(
            "private_fundamental_node", return_artifact("financial_reports")
        ),
        news=_agent_graph("private_news_node", return_artifact("news_analysis")),
        technical=_agent_graph(
            "private_technical_node", return_artifact("technical_analysis")
        ),
        debate=_agent_graph("private_debate_node", record_debate),
    )

    graph = build_root_graph(graphs).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "root-state-contract"}}
    graph.invoke(_run_input("Analyze Apple"), config=config)
    graph.invoke(_run_input("Analyze Microsoft"), config=config)

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
    assert len(debate_inputs) == 2
    second_debate_input = debate_inputs[-1]
    assert second_debate_input["company_profile"] == CompanyProfile(
        ticker="MSFT", name="MSFT"
    )
    references = second_debate_input["artifact_references"]
    assert isinstance(references, Mapping)
    assert set(references) == {
        "financial_reports",
        "news_analysis",
        "technical_analysis",
    }
    assert all(
        str(reference["artifact_id"]).startswith("msft-")
        for reference in references.values()
    )
    statuses = second_debate_input["workflow_activity_statuses"]
    assert isinstance(statuses, Mapping)
    assert set(statuses) == {
        "financial_reports-complete",
        "news_analysis-complete",
        "technical_analysis-complete",
        "consolidate_research",
    }
    assert all("aapl" not in key for key in statuses)
    logs = second_debate_input["error_logs"]
    assert isinstance(logs, list)
    assert {entry["node"] for entry in logs} == {
        "financial_reports",
        "news_analysis",
        "technical_analysis",
    }
    assert "intent_extraction" not in second_debate_input
    assert "fundamental_analysis" not in second_debate_input
    assert "financial_news_research" not in second_debate_input
    assert "technical_analysis" not in second_debate_input
    assert "debate" not in second_debate_input
