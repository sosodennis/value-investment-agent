from __future__ import annotations

from collections.abc import Callable

from src.agents.fundamental.domain.shared.contracts.traceable import (
    ManualProvenance,
    TraceableField,
)

from ...types import TraceInput

SEC_XBRL_RATIONALE = "Derived from SEC XBRL (financial reports)."


def build_base_params(*, ticker: str | None, rationale: str) -> dict[str, object]:
    return {
        "ticker": ticker or "UNKNOWN",
        "rationale": rationale,
    }


def build_sec_xbrl_base_params(*, ticker: str | None) -> dict[str, object]:
    return build_base_params(
        ticker=ticker,
        rationale=SEC_XBRL_RATIONALE,
    )


def build_capital_structure_params(
    *,
    cash: float | None,
    total_debt: float | None,
    preferred_stock: float | None,
    shares_outstanding: float | None,
    current_price: float | None,
) -> dict[str, float | None]:
    return {
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
    }


def build_capital_structure_trace_inputs(
    *,
    cash_tf: TraceableField[float],
    debt_tf: TraceableField[float],
    preferred_tf: TraceableField[float],
    shares_tf: TraceableField[float],
) -> dict[str, TraceInput]:
    return {
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }


def build_equity_value_params(
    *,
    shares_outstanding: float | None,
    current_price: float | None,
) -> dict[str, float | None]:
    return {
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
    }


def build_shares_trace_inputs(
    *,
    shares_tf: TraceableField[float],
) -> dict[str, TraceInput]:
    return {
        "shares_outstanding": shares_tf,
    }


def build_capm_market_trace_inputs(
    *,
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
    risk_free_description: str,
    beta_description: str,
    market_risk_premium_description: str,
) -> dict[str, TraceInput]:
    return {
        "risk_free_rate": TraceableField(
            name="Risk-Free Rate",
            value=risk_free_rate,
            provenance=ManualProvenance(
                description=risk_free_description,
                author="MarketDataService",
            ),
        ),
        "beta": TraceableField(
            name="Beta",
            value=beta,
            provenance=ManualProvenance(
                description=beta_description,
                author="MarketDataService",
            ),
        ),
        "market_risk_premium": TraceableField(
            name="Market Risk Premium",
            value=market_risk_premium,
            provenance=ManualProvenance(
                description=market_risk_premium_description,
                author="ValuationPolicy",
            ),
        ),
    }


def build_capm_market_params(
    *,
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
) -> dict[str, float]:
    return {
        "risk_free_rate": risk_free_rate,
        "beta": beta,
        "market_risk_premium": market_risk_premium,
    }


def build_monte_carlo_params(
    *,
    monte_carlo_iterations: int,
    monte_carlo_seed: int | None,
    monte_carlo_sampler: str,
) -> dict[str, int | str | None]:
    return {
        "monte_carlo_iterations": monte_carlo_iterations,
        "monte_carlo_seed": monte_carlo_seed,
        "monte_carlo_sampler": monte_carlo_sampler,
    }


def resolve_optional_trace_input(
    *,
    trace_input: TraceableField[float] | None,
    field_name: str,
    missing_reason: str,
    missing_field: Callable[[str, str], TraceableField[float]],
) -> TraceableField[float]:
    if trace_input is not None:
        return trace_input
    return missing_field(field_name, missing_reason)
