"""Compatibility exports for the shared debate artifact contract."""

from src.shared.artifacts.debate_contracts import (
    DebateArtifactModel,
    DebateHistoryMessageModel,
    EvidenceFactModel,
    ScenarioModel,
    parse_debate_artifact_model,
)

__all__ = [
    "DebateArtifactModel",
    "DebateHistoryMessageModel",
    "EvidenceFactModel",
    "ScenarioModel",
    "parse_debate_artifact_model",
]
