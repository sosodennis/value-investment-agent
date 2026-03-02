from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.agents.fundamental.domain.valuation.parameterization.contracts import (
    ParamBuildResult,
)
from src.agents.fundamental.interface.parsers import parse_calculation_metrics
from src.shared.kernel.types import JSONObject

from .valuation_execution_context_service import ValuationExecutionContext


@dataclass(frozen=True)
class ValuationExecutionResult:
    build_result: ParamBuildResult
    params_dump: JSONObject | None
    calculation_metrics: JSONObject | None
    calculation_error: str | None


def execute_valuation_calculation(
    *,
    context: ValuationExecutionContext,
    build_params_fn: Callable[
        [str, str | None, list[JSONObject], list[JSONObject] | None],
        ParamBuildResult,
    ],
) -> ValuationExecutionResult:
    build_result = build_params_fn(
        context.model_type,
        context.ticker,
        context.reports_raw,
        context.forward_signals,
    )

    if build_result.missing:
        return ValuationExecutionResult(
            build_result=build_result,
            params_dump=None,
            calculation_metrics=None,
            calculation_error=None,
        )

    params_dict = dict(build_result.params)
    params_dict["trace_inputs"] = build_result.trace_inputs

    schema = context.model_runtime.schema
    calculator = context.model_runtime.calculator
    params_obj = schema(**params_dict)
    params_dump = params_obj.model_dump(mode="json")
    if not isinstance(params_dump, dict):
        raise TypeError("valuation params must serialize to JSON object")

    calculation_metrics = parse_calculation_metrics(
        calculator(params_obj),
        context=f"{context.model_type} valuation calculation result",
    )
    raw_error = calculation_metrics.get("error")
    calculation_error = raw_error if isinstance(raw_error, str) and raw_error else None

    return ValuationExecutionResult(
        build_result=build_result,
        params_dump=params_dump,
        calculation_metrics=calculation_metrics,
        calculation_error=calculation_error,
    )
