from __future__ import annotations

from src.artifacts.application.ports import FiscalCurrentReadContext
from src.artifacts.application.service import ArtifactService


def build_default_artifact_service() -> ArtifactService:
    from src.artifacts.infrastructure.sqlalchemy_repository import (
        SqlAlchemyArtifactRepository,
    )

    return ArtifactService(repository=SqlAlchemyArtifactRepository())


__all__ = ["build_default_artifact_service"]


def build_default_fiscal_artifact_current_reader() -> FiscalCurrentReadContext:
    from src.agents.fundamental.entrypoint import (
        build_default_fiscal_artifact_current_reader as factory,
    )

    return factory()
