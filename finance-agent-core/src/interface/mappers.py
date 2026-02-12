"""
Output Mappers - Transform Graph State to UI Protocol

This module implements the Backend-for-Frontend (BFF) pattern, transforming
nested LangGraph state structures into flat, UI-ready payloads.

Design Principles:
1. Agents own their state structure (nested, context-rich)
2. Frontend owns its prop interface (flat, component-focused)
3. Mappers bridge the gap without polluting either side
"""

from collections.abc import Mapping
from typing import cast

from src.common.types import AgentOutputArtifactPayload


class NodeOutputMapper:
    """
    Centralized mapper for transforming agent outputs to UI payloads.

    Refactored to be GENERIC and DATA-DRIVEN (Standardization Phase 1).
    It no longer contains domain specific logic. It simply looks for the
    standard 'artifact' field in the state updates.
    """

    @staticmethod
    def _extract_artifact(value: object) -> AgentOutputArtifactPayload | None:
        """Helper to extract canonical artifact payload from a context dict."""
        if not isinstance(value, Mapping):
            return None
        artifact = value.get("artifact")
        if artifact is None:
            return None
        if not isinstance(artifact, dict):
            raise TypeError(f"Invalid artifact payload type: {type(artifact)!r}")
        return cast(AgentOutputArtifactPayload, artifact)

    @staticmethod
    def transform(
        agent_id: str, output: Mapping[str, object]
    ) -> AgentOutputArtifactPayload | None:
        """
        Extract AgentOutputArtifact from the state update for a specific agent.

        Strategy:
        1. Flat Pattern: Artifact exists directly in update (Subgraphs)
        2. Nested Pattern: Artifact is nested under agent's state key (Parent Graph)
        """
        # 1. Flat Pattern (Direct artifact)
        # Standard for subgraphs to enable immediate UI updates without sync barriers.
        if "artifact" in output:
            return NodeOutputMapper._extract_artifact(output)

        # 2. Nested Pattern (Artifact under agent key)
        # Used by parent graph nodes and final subgraph output adapters.
        if agent_id in output:
            return NodeOutputMapper._extract_artifact(output[agent_id])

        return None

    @staticmethod
    def map_all_outputs(
        graph_state: Mapping[str, object],
    ) -> dict[str, AgentOutputArtifactPayload]:
        """
        Scan the entire Graph State and extract all Agent Outputs.
        This is the only method the Server needs to call.
        """
        mapped_outputs: dict[str, AgentOutputArtifactPayload] = {}
        for key, value in graph_state.items():
            # Reuse the existing extraction logic
            artifact_data = NodeOutputMapper._extract_artifact(value)
            if artifact_data:
                mapped_outputs[key] = artifact_data
        return mapped_outputs
