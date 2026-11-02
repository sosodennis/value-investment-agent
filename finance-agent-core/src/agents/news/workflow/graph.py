from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from src.agents.news.application.factory import NewsWorkflowRunner

from .nodes import build_news_nodes
from .state import FinancialNewsInput, FinancialNewsOutput, FinancialNewsState


def build_news_workflow(runner: NewsWorkflowRunner) -> CompiledStateGraph:
    nodes = build_news_nodes(runner)
    builder = StateGraph(
        FinancialNewsState,
        input_schema=FinancialNewsInput,
        output_schema=FinancialNewsOutput,
    )
    builder.add_node(
        "search_node",
        nodes["search_node"],
        metadata={
            "agent_id": "financial_news_research",
            "workflow_activity_kind": "node",
            "workflow_scope_path": ("financial_news_research", "search-news"),
            "activity_label": "Search news",
        },
    )
    builder.add_node(
        "selector_node",
        nodes["selector_node"],
        metadata={
            "agent_id": "financial_news_research",
            "workflow_activity_kind": "node",
            "workflow_scope_path": ("financial_news_research", "select-articles"),
            "activity_label": "Select relevant articles",
        },
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "fetch_node",
        nodes["fetch_node"],
        metadata={
            "agent_id": "financial_news_research",
            "workflow_activity_kind": "node",
            "workflow_scope_path": ("financial_news_research", "fetch-articles"),
            "activity_label": "Fetch article content",
        },
    )
    builder.add_node(
        "analyst_node",
        nodes["analyst_node"],
        metadata={
            "agent_id": "financial_news_research",
            "workflow_activity_kind": "node",
            "workflow_scope_path": ("financial_news_research", "analyze-articles"),
            "activity_label": "Analyze articles",
        },
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "aggregator_node",
        nodes["aggregator_node"],
        metadata={
            "agent_id": "financial_news_research",
            "workflow_activity_kind": "node",
            "workflow_scope_path": ("financial_news_research", "aggregate-sentiment"),
            "activity_label": "Aggregate news sentiment",
        },
    )
    builder.add_edge(START, "search_node")
    return builder.compile()
