from __future__ import annotations

from collections.abc import Callable, Mapping

from src.shared.kernel.traceable import TraceableField


def resolve_reit_depreciation_for_affo(
    *,
    depreciation_tf: TraceableField[float],
    to_float: Callable[[object], float | None],
    assumptions: list[str],
) -> float:
    depreciation_and_amortization = to_float(depreciation_tf.value)
    if depreciation_and_amortization is None:
        assumptions.append("depreciation_and_amortization defaulted to 0.0 for AFFO")
        return 0.0
    return depreciation_and_amortization


def resolve_reit_maintenance_capex_ratio(
    *,
    market_snapshot: Mapping[str, object] | None,
    market_float: Callable[[Mapping[str, object] | None, str], float | None],
    default_maintenance_capex_ratio: float,
    assumptions: list[str],
) -> float:
    maintenance_capex_ratio = market_float(market_snapshot, "maintenance_capex_ratio")
    if maintenance_capex_ratio is None:
        assumptions.append(
            "maintenance_capex_ratio defaulted to "
            f"{default_maintenance_capex_ratio:.2f}"
        )
        return default_maintenance_capex_ratio
    return maintenance_capex_ratio
