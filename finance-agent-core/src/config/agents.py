"""
Centralized Agent Configuration (Python)

This module mirrors the frontend agent configuration and serves as the
single source of truth for agent metadata in the backend.
"""

# Agent configuration matching frontend/src/config/agents.ts
AGENT_CONFIGS = [
    {
        "id": "intent_extraction",
        "nodes": [
            "extraction",
            "searching",
            "deciding",
            "clarifying",
            "intent_extraction",
        ],
        "hide_token_streaming": ["extraction", "searching", "deciding", "clarifying"],
    },
    {
        "id": "fundamental_analysis",
        "nodes": ["financial_health", "model_selection", "fundamental_analysis"],
        "hide_token_streaming": [],
    },
    {
        "id": "financial_news_research",
        "nodes": [
            "search_node",
            "selector_node",
            "fetch_node",
            "analyst_node",
            "aggregator_node",
            "financial_news_research",
        ],
        "hide_token_streaming": ["selector_node", "analyst_node"],
    },
    {
        "id": "debate",
        "nodes": ["debate_aggregator", "bull", "bear", "moderator", "debate"],
        "hide_token_streaming": [],
    },
    {
        "id": "executor",
        "nodes": ["executor"],
        "hide_token_streaming": [],
    },
    {
        "id": "auditor",
        "nodes": ["auditor"],
        "hide_token_streaming": ["auditor"],
    },
    {
        "id": "approval",
        "nodes": ["approval"],
        "hide_token_streaming": [],
    },
    {
        "id": "calculator",
        "nodes": ["calculator"],
        "hide_token_streaming": [],
    },
]


def get_hidden_nodes() -> set[str]:
    """
    Get all nodes that should have token streaming hidden.

    Returns:
        Set of node names that should filter on_chat_model_stream events
    """
    hidden_nodes = set()

    for agent in AGENT_CONFIGS:
        for node in agent.get("hide_token_streaming", []):
            hidden_nodes.add(node)

    return hidden_nodes


def get_agent_id_from_node(node_name: str) -> str | None:
    """
    Map a node name to its parent agent ID.

    Args:
        node_name: The internal node name

    Returns:
        Agent ID if found, None otherwise
    """
    clean_node = node_name.lower().split(":")[-1]

    for agent in AGENT_CONFIGS:
        if clean_node in agent["nodes"]:
            return agent["id"]

    return None
