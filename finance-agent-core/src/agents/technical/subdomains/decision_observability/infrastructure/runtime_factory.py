from __future__ import annotations

from src.agents.technical.subdomains.decision_observability.application import (
    TechnicalDecisionObservabilityRuntimeService,
)
from src.agents.technical.subdomains.decision_observability.infrastructure.repository import (
    build_default_technical_decision_observability_repository,
)


def build_default_technical_decision_observability_runtime_service() -> (
    TechnicalDecisionObservabilityRuntimeService
):
    return TechnicalDecisionObservabilityRuntimeService(
        repository=build_default_technical_decision_observability_repository()
    )


__all__ = ["build_default_technical_decision_observability_runtime_service"]
