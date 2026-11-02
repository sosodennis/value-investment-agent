"""Stable construction boundary for technical artifact persistence."""


def build_default_technical_artifact_repository():
    from .infrastructure.technical_artifact_repository import (
        build_default_technical_artifact_repository as build_repository,
    )

    return build_repository()


__all__ = [
    "build_default_technical_artifact_repository",
]
