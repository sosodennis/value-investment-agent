from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BeforeValidator

from src.interface.artifacts.artifact_model_shared import (
    normalize_series_map,
    symbol,
    to_number,
    to_optional_string,
    to_string,
)

MEMORY_STRENGTH_MAP: dict[str, str] = {
    "structurally_stable": "structurally_stable",
    "balanced": "balanced",
    "fragile": "fragile",
}

STATISTICAL_STATE_MAP: dict[str, str] = {
    "equilibrium": "equilibrium",
    "deviating": "deviating",
    "anomaly": "anomaly",
    "statistical_anomaly": "anomaly",
}

RISK_LEVEL_MAP: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "critical": "critical",
    "high": "critical",
}


def _parse_fracdiff_number(value: object) -> float:
    return to_number(value, "frac_diff numeric")


def _parse_window_length(value: object) -> int:
    return int(to_number(value, "frac_diff.window_length"))


def _parse_memory_strength(value: object) -> str:
    return symbol(value, "frac_diff.memory_strength", MEMORY_STRENGTH_MAP)


def _parse_confluence_text(value: object) -> str:
    return to_string(value, "confluence string")


def _parse_statistical_strength(value: object) -> float:
    return to_number(value, "confluence.statistical_strength")


def _parse_z_score(value: object) -> float:
    return to_number(value, "signal_state.z_score")


def _parse_statistical_state(value: object) -> str:
    return symbol(value, "signal_state.statistical_state", STATISTICAL_STATE_MAP)


def _parse_signal_direction(value: object) -> str:
    return to_string(value, "signal_state.direction")


def _parse_risk_level(value: object) -> str:
    return symbol(value, "signal_state.risk_level", RISK_LEVEL_MAP)


def _parse_series_map_or_none(value: object) -> dict[str, float] | None:
    if value is None:
        return None
    return normalize_series_map(value, "raw_data.series")


def _parse_required_text(value: object) -> str:
    return to_string(value, "technical text")


def _parse_optional_text(value: object) -> str | None:
    return to_optional_string(value, "technical text")


def _parse_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        raise TypeError("technical.semantic_tags must be a list")
    return [to_string(item, "technical.semantic_tags[]") for item in value]


FracDiffNumber: TypeAlias = Annotated[float, BeforeValidator(_parse_fracdiff_number)]
WindowLength: TypeAlias = Annotated[int, BeforeValidator(_parse_window_length)]
MemoryStrength: TypeAlias = Annotated[
    Literal["structurally_stable", "balanced", "fragile"],
    BeforeValidator(_parse_memory_strength),
]

ConfluenceText: TypeAlias = Annotated[str, BeforeValidator(_parse_confluence_text)]
StatisticalStrength: TypeAlias = Annotated[
    float, BeforeValidator(_parse_statistical_strength)
]

ZScore: TypeAlias = Annotated[float, BeforeValidator(_parse_z_score)]
StatisticalState: TypeAlias = Annotated[
    Literal["equilibrium", "deviating", "anomaly"],
    BeforeValidator(_parse_statistical_state),
]
SignalDirection: TypeAlias = Annotated[str, BeforeValidator(_parse_signal_direction)]
RiskLevel: TypeAlias = Annotated[
    Literal["low", "medium", "critical"],
    BeforeValidator(_parse_risk_level),
]

NormalizedSeriesMap: TypeAlias = Annotated[
    dict[str, float] | None,
    BeforeValidator(_parse_series_map_or_none),
]

TechnicalText: TypeAlias = Annotated[str, BeforeValidator(_parse_required_text)]
OptionalTechnicalText: TypeAlias = Annotated[
    str | None,
    BeforeValidator(_parse_optional_text),
]
TechnicalStringList: TypeAlias = Annotated[
    list[str],
    BeforeValidator(_parse_string_list),
]
