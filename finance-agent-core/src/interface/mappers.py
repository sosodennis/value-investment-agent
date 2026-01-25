"""
Output Mappers - Transform Graph State to UI Protocol

This module implements the Backend-for-Frontend (BFF) pattern, transforming
nested LangGraph state structures into flat, UI-ready payloads.

Design Principles:
1. Agents own their state structure (nested, context-rich)
2. Frontend owns its prop interface (flat, component-focused)
3. Mappers bridge the gap without polluting either side
"""

# Mapping from agent_id (from metadata) to state key (in AgentState)
# This is necessary because some agents use different names for their state vs their ID
AGENT_STATE_KEY_MAP = {
    "fundamental_analysis": "fundamental",  # FA uses "fundamental" as state key
    "financial_news_research": "financial_news",  # News uses "financial_news"
    # Others use the same name for both
}


class NodeOutputMapper:
    """
    Centralized mapper for transforming agent outputs to UI payloads.

    Refactored to be GENERIC and DATA-DRIVEN (Standardization Phase 1).
    It no longer contains domain specific logic. It simply looks for the
    standard 'artifact' field in the state updates.
    """

    @staticmethod
    def _extract_artifact(value) -> dict | None:
        """Helper to extract artifact from a value (dict or Pydantic model)."""
        # Check for Pydantic model with artifact
        if hasattr(value, "artifact") and value.artifact:
            return (
                value.artifact.model_dump()
                if hasattr(value.artifact, "model_dump")
                else value.artifact
            )

        # Check for dict with artifact
        if isinstance(value, dict) and value.get("artifact"):
            val = value["artifact"]
            return val.model_dump() if hasattr(val, "model_dump") else val

        return None

    @staticmethod
    def transform(agent_id: str, output: dict) -> dict | None:
        """
        Extract AgentOutputArtifact from the state update for a specific agent.

        IMPORTANT: We must look for the artifact under the agent's OWN state key,
        not just return the first artifact we find. LangGraph events contain the
        entire accumulated state, so we'd otherwise return stale artifacts from
        previously-run agents.
        """
        if not isinstance(output, dict):
            return None

        # 1. Primary: Look for artifact under agent's own state key
        state_key = AGENT_STATE_KEY_MAP.get(
            agent_id, agent_id
        )  # e.g. "fundamental" for "fundamental_analysis"

        if state_key in output:
            result = NodeOutputMapper._extract_artifact(output[state_key])
            if result:
                return result

        # 2. Fallback: Also check for top-level artifact (legacy pattern)
        if "artifact" in output:
            val = output["artifact"]
            return val.model_dump() if hasattr(val, "model_dump") else val

        return None
