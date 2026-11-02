from __future__ import annotations

from src.artifacts.application.service import ArtifactService


def build_default_artifact_service() -> ArtifactService:
    from src.artifacts.infrastructure.sqlalchemy_repository import (
        SqlAlchemyArtifactRepository,
    )

    return ArtifactService(repository=SqlAlchemyArtifactRepository())


__all__ = ["build_default_artifact_service"]
