from __future__ import annotations

from .calculator_runtime_support import (
    apply_trace_inputs,
    compute_upside,
    unwrap_traceable_value,
)
from .dcf_variant_contracts import (
    DcfGraph,
    DcfGraphFactory,
    DcfMonteCarloPolicy,
    DcfVariantParams,
)
from .dcf_variant_distribution_service import run_dcf_variant_monte_carlo
from .dcf_variant_result_service import (
    build_dcf_variant_details,
    build_dcf_variant_raw_inputs,
    build_dcf_variant_static_inputs,
    extract_dcf_variant_converged_inputs,
)
from .dcf_variant_sensitivity_service import run_dcf_variant_sensitivity
from .dcf_variant_validation_service import validate_dcf_variant_projection_lengths


def calculate_dcf_variant_valuation(
    params: DcfVariantParams,
    *,
    graph_factory: DcfGraphFactory,
    monte_carlo_policy: DcfMonteCarloPolicy,
) -> dict[str, float | str | dict[str, object]]:
    graph: DcfGraph = graph_factory()

    validation_error = validate_dcf_variant_projection_lengths(params)
    if validation_error is not None:
        return {"error": validation_error}

    try:
        inputs = apply_trace_inputs(
            build_dcf_variant_raw_inputs(params),
            params.trace_inputs,
        )
        results = graph.calculate(inputs, trace=True)

        intrinsic_value = float(
            unwrap_traceable_value(results.get("intrinsic_value", 0.0))
        )
        upside = compute_upside(intrinsic_value, params.current_price)

        converged_inputs = extract_dcf_variant_converged_inputs(results)
        static_inputs = build_dcf_variant_static_inputs(params)
        details = build_dcf_variant_details(
            results=results,
            converged_inputs=converged_inputs,
        )
        _attach_dcf_variant_sensitivity(
            details=details,
            intrinsic_value=intrinsic_value,
            converged_inputs=converged_inputs,
            static_inputs=static_inputs,
            wacc=params.wacc,
            terminal_growth=params.terminal_growth,
            policy=monte_carlo_policy,
        )

        if params.monte_carlo_iterations > 0:
            details["distribution_summary"] = run_dcf_variant_monte_carlo(
                params=params,
                converged_inputs=converged_inputs,
                static_inputs=static_inputs,
                policy=monte_carlo_policy,
            )

        return {
            "ticker": params.ticker,
            "enterprise_value": float(
                unwrap_traceable_value(results.get("enterprise_value", 0.0))
            ),
            "equity_value": float(
                unwrap_traceable_value(results.get("equity_value", 0.0))
            ),
            "intrinsic_value": intrinsic_value,
            "upside_potential": upside,
            "details": details,
            "trace": results,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _attach_dcf_variant_sensitivity(
    *,
    details: dict[str, object],
    intrinsic_value: float,
    converged_inputs: dict[str, list[float]],
    static_inputs: dict[str, float],
    wacc: float,
    terminal_growth: float,
    policy: DcfMonteCarloPolicy,
) -> None:
    try:
        sensitivity = run_dcf_variant_sensitivity(
            base_intrinsic_value=intrinsic_value,
            converged_inputs=converged_inputs,
            static_inputs=static_inputs,
            base_wacc=float(wacc),
            base_terminal_growth=float(terminal_growth),
            policy=policy,
        )
    except Exception as exc:  # noqa: BLE001
        details["sensitivity_summary"] = {
            "enabled": False,
            "reason": f"error:{exc.__class__.__name__}",
        }
        return

    details["sensitivity_summary"] = {
        "enabled": True,
        "base_intrinsic_value": sensitivity["base_intrinsic_value"],
        "scenario_count": sensitivity["scenario_count"],
        "max_upside_delta_pct": sensitivity["max_upside_delta_pct"],
        "max_downside_delta_pct": sensitivity["max_downside_delta_pct"],
        "top_drivers": sensitivity["top_drivers"],
    }
    details["sensitivity_cases"] = sensitivity["cases"]


__all__ = [
    "DcfGraph",
    "DcfMonteCarloPolicy",
    "DcfVariantParams",
    "calculate_dcf_variant_valuation",
]
