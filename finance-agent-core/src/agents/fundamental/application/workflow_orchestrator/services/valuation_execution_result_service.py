from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.agents.fundamental.subdomains.core_valuation.domain.parameterization.contracts import (
    ParamBuildResult,
)
from src.agents.fundamental.subdomains.financial_statements.interface.parsers import (
    parse_calculation_metrics,
)
from src.agents.fundamental.subdomains.forward_signals.interface.contracts import (
    ForwardSignalPayload,
)
from src.shared.kernel.types import JSONObject

from .valuation_execution_context_service import ValuationExecutionContext


@dataclass(frozen=True)
class ValuationExecutionResult:
    build_result: ParamBuildResult
    params_dump: JSONObject | None
    calculation_metrics: JSONObject | None
    calculation_error: str | None
    audit_passed: bool | None
    audit_messages: list[str]
    audit_error: str | None


def _parse_audit_messages(raw: object) -> list[str]:
    if not isinstance(raw, list | tuple):
        raise TypeError("valuation auditor result.messages must be a list of strings")
    messages: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise TypeError(
                "valuation auditor result.messages must be a list of strings"
            )
        normalized = item.strip()
        if normalized:
            messages.append(normalized)
    return messages


def _parse_audit_result(raw: object) -> tuple[bool, list[str]]:
    passed_raw = getattr(raw, "passed", None)
    messages_raw = getattr(raw, "messages", None)
    if not isinstance(passed_raw, bool):
        raise TypeError("valuation auditor result.passed must be bool")
    messages = _parse_audit_messages(messages_raw)
    return passed_raw, messages


def _build_audit_failure_message(
    *,
    model_type: str,
    messages: list[str],
) -> str:
    fail_messages = [item for item in messages if item.startswith("FAIL:")]
    selected = fail_messages or messages
    detail = " | ".join(selected[:3]) if selected else "no failure detail"
    return f"Valuation audit failed for {model_type}: {detail}"


def execute_valuation_calculation(
    *,
    context: ValuationExecutionContext,
    build_params_fn: Callable[
        [str, str | None, list[JSONObject], list[ForwardSignalPayload] | None],
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
            audit_passed=None,
            audit_messages=[],
            audit_error=None,
        )

    params_dict = dict(build_result.params)
    params_dict["trace_inputs"] = build_result.trace_inputs

    schema = context.model_runtime.schema
    calculator = context.model_runtime.calculator
    auditor = context.model_runtime.auditor
    params_obj = schema(**params_dict)
    params_dump = params_obj.model_dump(mode="json")
    if not isinstance(params_dump, dict):
        raise TypeError("valuation params must serialize to JSON object")

    try:
        audit_result_raw = auditor(params_obj)
        audit_passed, audit_messages = _parse_audit_result(audit_result_raw)
    except Exception as exc:
        return ValuationExecutionResult(
            build_result=build_result,
            params_dump=params_dump,
            calculation_metrics=None,
            calculation_error=None,
            audit_passed=False,
            audit_messages=[],
            audit_error=f"Valuation audit execution failed for {context.model_type}: {str(exc)}",
        )

    if not audit_passed:
        return ValuationExecutionResult(
            build_result=build_result,
            params_dump=params_dump,
            calculation_metrics=None,
            calculation_error=None,
            audit_passed=False,
            audit_messages=audit_messages,
            audit_error=_build_audit_failure_message(
                model_type=context.model_type,
                messages=audit_messages,
            ),
        )

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
        audit_passed=True,
        audit_messages=audit_messages,
        audit_error=None,
    )
