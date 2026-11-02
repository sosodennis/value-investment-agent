"""Stable public contracts for technical interpretation."""

from .domain.interpretation_guardrail_service import (
    INTERPRETATION_GUARDRAIL_VERSION,
    InterpretationGuardrailOutcome,
    apply_interpretation_guardrail,
)


def build_default_technical_interpretation_provider(*, llm_provider, llm_route):
    from .infrastructure.technical_interpretation_provider import (
        TechnicalInterpretationProvider,
    )

    return TechnicalInterpretationProvider(
        llm_provider=llm_provider,
        llm_route=llm_route,
    )


__all__ = [
    "INTERPRETATION_GUARDRAIL_VERSION",
    "InterpretationGuardrailOutcome",
    "apply_interpretation_guardrail",
    "build_default_technical_interpretation_provider",
]
