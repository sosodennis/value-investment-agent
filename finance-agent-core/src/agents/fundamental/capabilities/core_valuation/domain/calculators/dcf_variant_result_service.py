from __future__ import annotations

from collections.abc import Mapping

from .calculator_runtime_support import unwrap_traceable_value
from .dcf_variant_contracts import DcfVariantParams
from .dcf_variant_validation_service import coerce_float_list


def build_dcf_variant_raw_inputs(params: DcfVariantParams) -> dict[str, object]:
    return {
        "initial_revenue": params.initial_revenue,
        "growth_rates": params.growth_rates,
        "operating_margins": params.operating_margins,
        "tax_rate": params.tax_rate,
        "da_rates": params.da_rates,
        "capex_rates": params.capex_rates,
        "wc_rates": params.wc_rates,
        "sbc_rates": params.sbc_rates,
        "wacc": params.wacc,
        "terminal_growth": params.terminal_growth,
        "cash": params.cash,
        "total_debt": params.total_debt,
        "preferred_stock": params.preferred_stock,
        "shares_outstanding": params.shares_outstanding,
    }


def extract_dcf_variant_converged_inputs(
    results: Mapping[str, object],
) -> dict[str, list[float]]:
    return {
        "growth_rates_converged": coerce_float_list(
            unwrap_traceable_value(results.get("growth_rates_converged", [])),
            field_name="growth_rates_converged",
        ),
        "operating_margins_converged": coerce_float_list(
            unwrap_traceable_value(results.get("operating_margins_converged", [])),
            field_name="operating_margins_converged",
        ),
        "da_rates_converged": coerce_float_list(
            unwrap_traceable_value(results.get("da_rates_converged", [])),
            field_name="da_rates_converged",
        ),
        "capex_rates_converged": coerce_float_list(
            unwrap_traceable_value(results.get("capex_rates_converged", [])),
            field_name="capex_rates_converged",
        ),
        "wc_rates_converged": coerce_float_list(
            unwrap_traceable_value(results.get("wc_rates_converged", [])),
            field_name="wc_rates_converged",
        ),
        "sbc_rates_converged": coerce_float_list(
            unwrap_traceable_value(results.get("sbc_rates_converged", [])),
            field_name="sbc_rates_converged",
        ),
    }


def build_dcf_variant_details(
    *,
    results: Mapping[str, object],
    converged_inputs: Mapping[str, list[float]],
) -> dict[str, object]:
    return {
        "fcff": unwrap_traceable_value(results.get("fcff", [])),
        "projected_revenue": unwrap_traceable_value(
            results.get("projected_revenue", [])
        ),
        "reinvestment_rates": unwrap_traceable_value(
            results.get("reinvestment_rates", [])
        ),
        "growth_rates_converged": converged_inputs["growth_rates_converged"],
        "operating_margins_converged": converged_inputs["operating_margins_converged"],
        "da_rates_converged": converged_inputs["da_rates_converged"],
        "capex_rates_converged": converged_inputs["capex_rates_converged"],
        "wc_rates_converged": converged_inputs["wc_rates_converged"],
        "sbc_rates_converged": converged_inputs["sbc_rates_converged"],
        "terminal_growth_effective": float(
            unwrap_traceable_value(results.get("terminal_growth_effective", 0.0))
        ),
        "pv_fcff": float(unwrap_traceable_value(results.get("pv_fcff", 0.0))),
        "terminal_value": float(
            unwrap_traceable_value(results.get("terminal_value", 0.0))
        ),
        "pv_terminal": float(unwrap_traceable_value(results.get("pv_terminal", 0.0))),
        "enterprise_value": float(
            unwrap_traceable_value(results.get("enterprise_value", 0.0))
        ),
    }


def build_dcf_variant_static_inputs(params: DcfVariantParams) -> dict[str, float]:
    return {
        "initial_revenue": float(params.initial_revenue),
        "tax_rate": float(params.tax_rate),
        "cash": float(params.cash),
        "total_debt": float(params.total_debt),
        "preferred_stock": float(params.preferred_stock),
        "shares_outstanding": float(params.shares_outstanding),
    }
