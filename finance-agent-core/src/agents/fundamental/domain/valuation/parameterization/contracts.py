from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from src.shared.kernel.types import JSONObject

from ..report_contract import FinancialReport
from .types import TraceInput


@dataclass(frozen=True)
class ParamBuildResult:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    metadata: JSONObject = field(default_factory=dict)


ModelParamBuilder = Callable[
    [str | None, FinancialReport, list[FinancialReport], Mapping[str, object] | None],
    ParamBuildResult,
]


class ParamBuilderPayload(Protocol):
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    shares_source: str


__all__ = ["ModelParamBuilder", "ParamBuildResult", "ParamBuilderPayload"]
