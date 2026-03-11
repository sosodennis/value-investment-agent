from __future__ import annotations

from src.agents.fundamental.core_valuation.domain.value_objects import (
    MODEL_TYPE_BY_SELECTION,
)


def resolve_calculator_model_type(selected_model_value: str) -> str:
    model = MODEL_TYPE_BY_SELECTION.get(selected_model_value)
    if model is None:
        return MODEL_TYPE_BY_SELECTION["dcf_standard"].value
    return model.value


__all__ = ["resolve_calculator_model_type"]
