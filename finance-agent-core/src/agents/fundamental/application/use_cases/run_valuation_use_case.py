from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Protocol

from src.agents.fundamental.application.services.valuation_completion_fields_service import (
    build_forward_signal_completion_fields,
    build_monte_carlo_completion_fields,
)
from src.agents.fundamental.application.services.valuation_execution_context_service import (
    resolve_valuation_execution_context,
)
from src.agents.fundamental.application.services.valuation_execution_result_service import (
    execute_valuation_calculation,
)
from src.agents.fundamental.domain.valuation.parameterization.contracts import (
    ParamBuildResult,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
FundamentalNodeResult = WorkflowNodeResult


class ValuationRuntime(Protocol):
    async def load_financial_reports_bundle(
        self, artifact_id: str
    ) -> tuple[list[JSONObject], list[JSONObject] | None] | None: ...

    def build_valuation_missing_inputs_update(
        self,
        *,
        fundamental: dict[str, object],
        missing_inputs: list[str],
        assumptions: list[str],
    ) -> JSONObject: ...

    def build_valuation_success_update(
        self,
        *,
        fundamental: dict[str, object],
        intent_ctx: dict[str, object],
        ticker: str | None,
        model_type: str,
        reports_raw: list[JSONObject],
        reports_artifact_id: str,
        params_dump: JSONObject,
        calculation_metrics: JSONObject,
        assumptions: list[str],
        build_metadata: JSONObject | None = None,
    ) -> JSONObject: ...

    def build_valuation_error_update(self, error: str) -> JSONObject: ...


def _log_build_result_policy_events(
    *,
    model_type: str,
    build_result: ParamBuildResult,
) -> None:
    if build_result.assumptions:
        log_event(
            logger,
            event="fundamental_valuation_assumptions_applied",
            message="controlled valuation assumptions applied",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_ASSUMPTIONS_APPLIED",
            fields={
                "model_type": model_type,
                "assumption_count": len(build_result.assumptions),
                "assumptions": build_result.assumptions,
            },
        )

    if isinstance(build_result.metadata, Mapping):
        forward_signal_raw = build_result.metadata.get("forward_signal")
        if isinstance(forward_signal_raw, Mapping):
            log_event(
                logger,
                event="fundamental_forward_signal_policy_applied",
                message="forward signal policy summary recorded",
                fields={
                    "model_type": model_type,
                    "signals_total": forward_signal_raw.get("signals_total"),
                    "signals_accepted": forward_signal_raw.get("signals_accepted"),
                    "signals_rejected": forward_signal_raw.get("signals_rejected"),
                    "growth_adjustment_basis_points": forward_signal_raw.get(
                        "growth_adjustment_basis_points"
                    ),
                    "margin_adjustment_basis_points": forward_signal_raw.get(
                        "margin_adjustment_basis_points"
                    ),
                    "forward_signal_risk_level": forward_signal_raw.get("risk_level"),
                    "source_types": forward_signal_raw.get("source_types"),
                },
            )


async def run_valuation_use_case(
    runtime: ValuationRuntime,
    state: Mapping[str, object],
    *,
    build_params_fn: Callable[
        [str, str | None, list[JSONObject], list[JSONObject] | None],
        ParamBuildResult,
    ],
    get_model_runtime_fn: Callable[[str], object | None],
) -> FundamentalNodeResult:
    log_event(
        logger,
        event="fundamental_valuation_started",
        message="fundamental valuation started",
    )

    try:
        execution_context = await resolve_valuation_execution_context(
            runtime=runtime,
            state=state,
            get_model_runtime_fn=get_model_runtime_fn,
        )
        model_type = execution_context.model_type
        ticker = execution_context.ticker

        execution_result = execute_valuation_calculation(
            context=execution_context,
            build_params_fn=build_params_fn,
        )
        build_result = execution_result.build_result

        _log_build_result_policy_events(
            model_type=model_type,
            build_result=build_result,
        )

        if build_result.missing:
            log_event(
                logger,
                event="fundamental_valuation_missing_inputs",
                message="fundamental valuation missing required inputs",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_VALUATION_INPUTS_MISSING",
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    "missing_inputs": build_result.missing,
                    "assumptions": build_result.assumptions,
                },
            )
            return FundamentalNodeResult(
                update=runtime.build_valuation_missing_inputs_update(
                    fundamental=execution_context.fundamental,
                    missing_inputs=build_result.missing,
                    assumptions=build_result.assumptions,
                ),
                goto="END",
            )

        if execution_result.calculation_error:
            log_event(
                logger,
                event="fundamental_valuation_calculation_error",
                message="valuation calculator returned error payload",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_VALUATION_CALCULATION_ERROR",
                fields={
                    "ticker": ticker,
                    "model_type": model_type,
                    "error": execution_result.calculation_error,
                },
            )
            return FundamentalNodeResult(
                update=runtime.build_valuation_error_update(
                    execution_result.calculation_error
                ),
                goto="END",
            )

        params_dump = execution_result.params_dump
        calculation_metrics = execution_result.calculation_metrics
        if params_dump is None or calculation_metrics is None:
            raise RuntimeError(
                "valuation calculation result is missing params_dump or metrics"
            )

        mc_completion_fields = build_monte_carlo_completion_fields(calculation_metrics)
        forward_signal_completion_fields = build_forward_signal_completion_fields(
            forward_signals=execution_context.forward_signals,
            build_metadata=(
                build_result.metadata
                if isinstance(build_result.metadata, Mapping)
                else None
            ),
        )
        log_event(
            logger,
            event="fundamental_valuation_completed",
            message="fundamental valuation completed",
            fields={
                "ticker": ticker,
                "model_type": model_type,
                **mc_completion_fields,
                **forward_signal_completion_fields,
            },
        )

        return FundamentalNodeResult(
            update=runtime.build_valuation_success_update(
                fundamental=execution_context.fundamental,
                intent_ctx=execution_context.intent_ctx,
                ticker=ticker,
                model_type=model_type,
                reports_raw=execution_context.reports_raw,
                reports_artifact_id=execution_context.reports_artifact_id,
                params_dump=params_dump,
                calculation_metrics=calculation_metrics,
                assumptions=build_result.assumptions,
                build_metadata=build_result.metadata,
            ),
            goto="END",
        )
    except Exception as exc:
        log_event(
            logger,
            event="fundamental_valuation_failed",
            message="fundamental valuation failed",
            level=logging.ERROR,
            error_code="FUNDAMENTAL_VALUATION_FAILED",
            fields={"exception": str(exc)},
        )
        return FundamentalNodeResult(
            update=runtime.build_valuation_error_update(str(exc)),
            goto="END",
        )
