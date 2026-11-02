from __future__ import annotations

from .decision_observability_runtime_service import (
    TechnicalDecisionObservabilityRuntimeService,
)


def build_default_technical_decision_observability_runtime_service() -> (
    TechnicalDecisionObservabilityRuntimeService
):
    from ..infrastructure.repository import (
        build_default_technical_decision_observability_repository,
    )

    return TechnicalDecisionObservabilityRuntimeService(
        repository=build_default_technical_decision_observability_repository()
    )


__all__ = ["build_default_technical_decision_observability_runtime_service"]
