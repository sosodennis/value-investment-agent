from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import ManualProvenance, TraceableField

from ..report_contract import FinancialReport, RealEstateExtension

TraceInput = TraceableField[float] | TraceableField[list[float]]


@dataclass(frozen=True)
class ReitBuilderDeps:
    default_maintenance_capex_ratio: float
    resolve_shares_outstanding: Callable[
        [TraceableField[float], Mapping[str, object] | None, list[str]],
        TraceableField[float],
    ]
    market_float: Callable[[Mapping[str, object] | None, str], float | None]
    value_or_missing: Callable[
        [TraceableField[float] | None, str, list[str]],
        float | None,
    ]
    resolve_monte_carlo_controls: Callable[
        [Mapping[str, object] | None, list[str]],
        tuple[int, int | None],
    ]
    to_float: Callable[[object], float | None]
    missing_field: Callable[[str, str], TraceableField[float]]


@dataclass(frozen=True)
class ReitBuildPayload:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    shares_source: str


def build_reit_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
    deps: ReitBuilderDeps,
) -> ReitBuildPayload:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base
    extension = (
        latest.extension if isinstance(latest.extension, RealEstateExtension) else None
    )

    ffo_tf = extension.ffo if extension else None
    shares_tf = deps.resolve_shares_outstanding(
        base.shares_outstanding,
        market_snapshot,
        assumptions,
    )
    market_shares = deps.market_float(market_snapshot, "shares_outstanding")
    shares_source = (
        "market_data" if market_shares is not None and market_shares > 0 else "filing"
    )
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock
    depreciation_tf = base.depreciation_and_amortization

    ffo = deps.value_or_missing(ffo_tf, "ffo", missing)
    shares_outstanding = deps.value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = deps.value_or_missing(cash_tf, "cash", missing)
    total_debt = deps.value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = deps.value_or_missing(preferred_tf, "preferred_stock", missing)
    current_price = deps.market_float(market_snapshot, "current_price")
    monte_carlo_iterations, monte_carlo_seed = deps.resolve_monte_carlo_controls(
        market_snapshot, assumptions
    )

    depreciation_and_amortization = deps.to_float(depreciation_tf.value)
    if depreciation_and_amortization is None:
        depreciation_and_amortization = 0.0
        assumptions.append("depreciation_and_amortization defaulted to 0.0 for AFFO")

    maintenance_capex_ratio = deps.market_float(
        market_snapshot, "maintenance_capex_ratio"
    )
    if maintenance_capex_ratio is None:
        maintenance_capex_ratio = deps.default_maintenance_capex_ratio
        assumptions.append(
            "maintenance_capex_ratio defaulted to "
            f"{deps.default_maintenance_capex_ratio:.2f}"
        )

    missing.append("ffo_multiple")

    trace_inputs: dict[str, TraceInput] = {
        "ffo": ffo_tf
        if ffo_tf is not None
        else deps.missing_field("FFO", "Missing FFO"),
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
        "depreciation_and_amortization": depreciation_tf,
        "maintenance_capex_ratio": TraceableField(
            name="Maintenance CapEx Ratio",
            value=maintenance_capex_ratio,
            provenance=ManualProvenance(
                description="Configurable REIT maintenance capex heuristic ratio",
                author="ValuationPolicy",
            ),
        ),
    }

    params: dict[str, object] = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "ffo": ffo,
        "ffo_multiple": None,
        "depreciation_and_amortization": depreciation_and_amortization,
        "maintenance_capex_ratio": maintenance_capex_ratio,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
        "monte_carlo_iterations": monte_carlo_iterations,
        "monte_carlo_seed": monte_carlo_seed,
    }

    return ReitBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )
