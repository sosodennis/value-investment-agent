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
        details = build_dcf_variant_details(
            results=results,
            converged_inputs=converged_inputs,
        )

        if params.monte_carlo_iterations > 0:
            details["distribution_summary"] = run_dcf_variant_monte_carlo(
                params=params,
                converged_inputs=converged_inputs,
                static_inputs=build_dcf_variant_static_inputs(params),
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


__all__ = [
    "DcfGraph",
    "DcfMonteCarloPolicy",
    "DcfVariantParams",
    "calculate_dcf_variant_valuation",
]
