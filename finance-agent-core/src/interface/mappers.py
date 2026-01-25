"""
Output Mappers - Transform Graph State to UI Protocol

This module implements the Backend-for-Frontend (BFF) pattern, transforming
nested LangGraph state structures into flat, UI-ready payloads.

Design Principles:
1. Agents own their state structure (nested, context-rich)
2. Frontend owns its prop interface (flat, component-focused)
3. Mappers bridge the gap without polluting either side
"""


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

        Strategy:
        1. Flat Pattern: Artifact exists directly in update (Subgraphs)
        2. Nested Pattern: Artifact is nested under agent's state key (Parent Graph)
        """
        if not isinstance(output, dict):
            return None

        # 1. Flat Pattern (Direct artifact)
        # Standard for subgraphs to enable immediate UI updates without sync barriers.
        if "artifact" in output:
            return NodeOutputMapper._extract_artifact(output)

        # 2. Nested Pattern (Artifact under agent key)
        # Used by parent graph nodes and final subgraph output adapters.
        if agent_id in output:
            return NodeOutputMapper._extract_artifact(output[agent_id])

        return None
