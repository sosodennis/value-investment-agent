from __future__ import annotations

from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .state import AgentState


def _mark_research_consolidated(_state: AgentState) -> dict[str, object]:
    """Record the root-level fan-in after all research agents have completed."""
    return {"workflow_activity_statuses": {"consolidate_research": "done"}}


@dataclass(frozen=True)
class RootAgentGraphs:
    intent: CompiledStateGraph
    fundamental: CompiledStateGraph
    news: CompiledStateGraph
    technical: CompiledStateGraph
    debate: CompiledStateGraph


def build_root_graph(graphs: RootAgentGraphs) -> StateGraph:
    builder = StateGraph(AgentState)
    builder.add_node(
        "intent_agent",
        graphs.intent,
        metadata={
            "agent_id": "intent_extraction",
            "workflow_activity_kind": "agent",
            "workflow_scope_path": ("intent_extraction",),
            "activity_label": "Resolve company",
        },
    )
    builder.add_node(
        "fundamental_agent",
        graphs.fundamental,
        metadata={
            "agent_id": "fundamental_analysis",
            "workflow_activity_kind": "agent",
            "workflow_scope_path": ("fundamental_analysis",),
            "activity_label": "Analyze fundamentals",
        },
    )
    builder.add_node(
        "news_agent",
        graphs.news,
        metadata={
            "agent_id": "financial_news_research",
            "workflow_activity_kind": "agent",
            "workflow_scope_path": ("financial_news_research",),
            "activity_label": "Research financial news",
        },
    )
    builder.add_node(
        "technical_agent",
        graphs.technical,
        metadata={
            "agent_id": "technical_analysis",
            "workflow_activity_kind": "agent",
            "workflow_scope_path": ("technical_analysis",),
            "activity_label": "Analyze technical signals",
        },
    )
    builder.add_node(
        "consolidate_research",
        _mark_research_consolidated,
        metadata={
            "workflow_scope_path": ("research", "consolidate"),
            "activity_label": "Consolidate research",
        },
    )
    builder.add_node(
        "debate_agent",
        graphs.debate,
        metadata={
            "agent_id": "debate",
            "workflow_activity_kind": "agent",
            "workflow_scope_path": ("debate",),
            "activity_label": "Review the investment case",
        },
    )

    builder.add_edge(START, "intent_agent")
    builder.add_edge("intent_agent", "fundamental_agent")
    builder.add_edge("intent_agent", "news_agent")
    builder.add_edge("intent_agent", "technical_agent")
    builder.add_edge(
        ["fundamental_agent", "news_agent", "technical_agent"],
        "consolidate_research",
    )
    builder.add_edge("consolidate_research", "debate_agent")
    builder.add_edge("debate_agent", END)
    return builder
