"""
Centralized Agent Configuration (Python)

This module mirrors the frontend agent configuration and serves as the
single source of truth for agent metadata in the backend.
"""

# Agent configuration matching frontend/src/config/agents.ts
AGENT_CONFIGS = [
    {
        "id": "intent_extraction",
        "name": "Intent Planner",
        "nodes": [
            "intent_extraction",
            "intent_agent",
            "prepare_intent",
            "process_intent",
        ],
        "hide_token_streaming": [
            "extraction",
            "searching",
            "deciding",
            "clarifying",
            "prepare_intent",
            "process_intent",
        ],
    },
    {
        "id": "fundamental_analysis",
        "name": "Fundamental Analyst",
        "nodes": [
            "fundamental_analysis",
            "fundamental_agent",
            "prepare_fundamental",
            "process_fundamental",
            "financial_health",  # Subgraph Node
            "model_selection",  # Subgraph Node
        ],
        "hide_token_streaming": ["prepare_fundamental", "process_fundamental"],
    },
    {
        "id": "technical_analysis",
        "name": "Technical Analyst",
        "nodes": [
            "technical_analysis",
            "technical_agent",
            "prepare_technical",
            "process_technical",
            "data_fetch",  # Subgraph Node
            "fracdiff_compute",  # Subgraph Node
            "semantic_translate",  # Subgraph Node
        ],
        "hide_token_streaming": [
            "data_fetch",
            "fracdiff_compute",
            "prepare_technical",
            "process_technical",
        ],
    },
    {
        "id": "financial_news_research",
        "name": "Financial News",
        "nodes": [
            "financial_news_research",
            "news_agent",
            "prepare_news",
            "process_news",
            "search_node",  # Subgraph Node
            "selector_node",  # Subgraph Node
            "fetch_node",  # Subgraph Node
            "analyst_node",  # Subgraph Node
            "aggregator_node",  # Subgraph Node
        ],
        "hide_token_streaming": [
            "selector_node",
            "analyst_node",
            "prepare_news",
            "process_news",
        ],
    },
    {
        "id": "debate",
        "name": "Debate Arena",
        "nodes": [
            "debate",
            "debate_agent",
            "prepare_debate",
            "process_debate",
            "debate_aggregator",  # Subgraph Node
            "r1_bull",  # Subgraph Node
            "r1_bear",  # Subgraph Node
            "r1_moderator",  # Subgraph Node
            "r2_bull",  # Subgraph Node
            "r2_bear",  # Subgraph Node
            "r2_moderator",  # Subgraph Node
            "r3_bull",  # Subgraph Node
            "r3_bear",  # Subgraph Node
            "verdict",  # Subgraph Node
        ],
        "hide_token_streaming": ["prepare_debate", "process_debate"],
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
        "name": "Chief Auditor",
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
