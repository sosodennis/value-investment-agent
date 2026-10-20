"""Stable artifact contracts for fundamental analysis."""

from .interface.contracts import (
    FundamentalArtifactModel,
    parse_fundamental_artifact_model,
)

__all__ = ["FundamentalArtifactModel", "parse_fundamental_artifact_model"]
