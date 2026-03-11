from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from src.agents.fundamental.financial_statements.interface.parsers import (
    ValuationModelRuntime,
    parse_valuation_model_runtime,
)
from src.agents.fundamental.workflow_orchestrator.application.state_readers import (
    read_fundamental_state,
    read_intent_state,
)
from src.shared.kernel.types import JSONObject


class ValuationBundleRuntime(Protocol):
    async def load_financial_reports_bundle(
        self,
        artifact_id: str,
    ) -> tuple[list[JSONObject], list[JSONObject] | None] | None: ...


@dataclass(frozen=True)
class ValuationExecutionContext:
    fundamental: dict[str, object]
    model_type: str
    intent_ctx: dict[str, object]
    ticker: str | None
    reports_artifact_id: str
    reports_raw: list[JSONObject]
    forward_signals: list[JSONObject] | None
    model_runtime: ValuationModelRuntime


async def resolve_valuation_execution_context(
    *,
    runtime: ValuationBundleRuntime,
    state: Mapping[str, object],
    get_model_runtime_fn: Callable[[str], object | None],
) -> ValuationExecutionContext:
    fundamental_state = read_fundamental_state(state)
    fundamental = fundamental_state.context
    model_type = fundamental_state.model_type

    intent_state = read_intent_state(state)
    intent_ctx = intent_state.context
    ticker = intent_state.resolved_ticker

    if model_type is None:
        raise ValueError("Missing model_type for valuation calculation")

    model_runtime = parse_valuation_model_runtime(
        get_model_runtime_fn(model_type),
        context=f"valuation model runtime for {model_type}",
    )

    reports_artifact_id = fundamental_state.financial_reports_artifact_id
    if reports_artifact_id is None:
        raise ValueError("Missing financial_reports_artifact_id for valuation")

    bundle = await runtime.load_financial_reports_bundle(reports_artifact_id)
    if bundle is None:
        raise ValueError("Missing financial reports artifact data for valuation")

    reports_raw, forward_signals = bundle
    if not reports_raw:
        raise ValueError("Empty financial reports data for valuation")

    return ValuationExecutionContext(
        fundamental=dict(fundamental),
        model_type=model_type,
        intent_ctx=intent_ctx,
        ticker=ticker,
        reports_artifact_id=reports_artifact_id,
        reports_raw=reports_raw,
        forward_signals=forward_signals,
        model_runtime=model_runtime,
    )
