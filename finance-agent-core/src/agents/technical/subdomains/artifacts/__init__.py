"""artifacts subdomain facade."""

from .infrastructure import (
    TechnicalArtifactRepository,
    build_default_technical_artifact_repository,
)

__all__ = [
    "TechnicalArtifactRepository",
    "build_default_technical_artifact_repository",
]
