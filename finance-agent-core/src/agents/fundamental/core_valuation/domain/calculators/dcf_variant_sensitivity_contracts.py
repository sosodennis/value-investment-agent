from __future__ import annotations

from typing import Literal, TypedDict

ShockDimension = Literal[
    "wacc",
    "terminal_growth",
    "growth_level",
    "margin_level",
]


class DcfSensitivityCase(TypedDict):
    scenario_id: str
    shock_dimension: ShockDimension
    shock_value_bp: int
    intrinsic_value: float
    delta_pct_vs_base: float
    guard_applied: bool


class DcfSensitivitySummary(TypedDict):
    base_intrinsic_value: float
    scenario_count: int
    max_upside_delta_pct: float
    max_downside_delta_pct: float
    top_drivers: list[DcfSensitivityCase]
    cases: list[DcfSensitivityCase]
