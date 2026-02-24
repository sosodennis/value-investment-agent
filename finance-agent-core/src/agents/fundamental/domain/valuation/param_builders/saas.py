from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import ManualProvenance, TraceableField

from ..assumptions import (
    DEFAULT_DA_RATE,
    DEFAULT_TERMINAL_GROWTH,
    assume_rate,
)
from ..report_contract import FinancialReport, IndustrialExtension

TraceInput = TraceableField[float] | TraceableField[list[float]]

DEFAULT_SAAS_RISK_FREE_RATE = 0.042
DEFAULT_SAAS_BETA = 1.0
WACC_FLOOR = 0.05
WACC_CEILING = 0.30
TERMINAL_GROWTH_FLOOR = -0.02
TERMINAL_GROWTH_CEILING = 0.04
TERMINAL_GROWTH_SPREAD_BUFFER = 0.005


@dataclass(frozen=True)
class SaasBuilderDeps:
    projection_years: int
    default_market_risk_premium: float
    resolve_shares_outstanding: Callable[
        [TraceableField[float], Mapping[str, object] | None, list[str]],
        TraceableField[float],
    ]
    market_float: Callable[[Mapping[str, object] | None, str], float | None]
    value_or_missing: Callable[
        [TraceableField[float] | None, str, list[str]],
        float | None,
    ]
    ratio: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ]
    subtract: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ]
    build_growth_rates: Callable[
        [list[TraceableField[float]], Mapping[str, object] | None, list[str]],
        TraceableField[list[float]],
    ]
    repeat_rate: Callable[
        [str, TraceableField[float], int], TraceableField[list[float]]
    ]
    resolve_monte_carlo_controls: Callable[
        [Mapping[str, object] | None, list[str]],
        tuple[int, int | None],
    ]
    missing_field: Callable[[str, str], TraceableField[float]]


@dataclass(frozen=True)
class SaasBuildPayload:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    shares_source: str


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def build_saas_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
    deps: SaasBuilderDeps,
) -> SaasBuildPayload:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base
    extension = (
        latest.extension if isinstance(latest.extension, IndustrialExtension) else None
    )

    revenue_tf = base.total_revenue
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

    operating_income_tf = base.operating_income
    tax_expense_tf = base.income_tax_expense
    income_before_tax_tf = base.income_before_tax
    da_tf = base.depreciation_and_amortization
    sbc_tf = base.share_based_compensation
    capex_tf = extension.capex if extension else None

    current_assets_tf = base.current_assets
    current_liabilities_tf = base.current_liabilities

    margin_tf = deps.ratio(
        "Operating Margin",
        operating_income_tf,
        revenue_tf,
        "OperatingIncome / Revenue",
    )
    tax_rate_tf = deps.ratio(
        "Tax Rate",
        tax_expense_tf,
        income_before_tax_tf,
        "IncomeTaxExpense / IncomeBeforeTax",
    )
    da_rate_tf = deps.ratio(
        "D&A Rate",
        da_tf,
        revenue_tf,
        "DepreciationAndAmortization / Revenue",
    )
    if da_rate_tf.value is None:
        da_rate_tf = assume_rate(
            "D&A Rate",
            DEFAULT_DA_RATE,
            "Policy default D&A rate (preview only; requires analyst review)",
        )
        assumptions.append(f"da_rates defaulted to {DEFAULT_DA_RATE:.2%}")

    capex_rate_tf = (
        deps.ratio("CapEx Rate", capex_tf, revenue_tf, "CapEx / Revenue")
        if capex_tf is not None
        else deps.missing_field("CapEx Rate", "Missing CapEx for CapEx Rate")
    )
    sbc_rate_tf = deps.ratio(
        "SBC Rate",
        sbc_tf,
        revenue_tf,
        "ShareBasedCompensation / Revenue",
    )

    wc_latest = deps.subtract(
        "Working Capital (Latest)",
        current_assets_tf,
        current_liabilities_tf,
        "CurrentAssets - CurrentLiabilities",
    )
    wc_prev = None
    if len(reports) > 1:
        prev = reports[1]
        wc_prev = deps.subtract(
            "Working Capital (Previous)",
            prev.base.current_assets,
            prev.base.current_liabilities,
            "Prev CurrentAssets - Prev CurrentLiabilities",
        )

    if (
        wc_prev is not None
        and wc_prev.value is not None
        and wc_latest.value is not None
    ):
        wc_delta = deps.subtract(
            "Working Capital Delta",
            wc_latest,
            wc_prev,
            "WorkingCapitalLatest - WorkingCapitalPrevious",
        )
        wc_rate_tf = deps.ratio("WC Rate", wc_delta, revenue_tf, "ChangeInWC / Revenue")
    else:
        wc_rate_tf = deps.missing_field("WC Rate", "Missing working capital history")

    revenue_series = [report.base.total_revenue for report in reports]
    growth_rates_tf = deps.build_growth_rates(
        revenue_series, market_snapshot, assumptions
    )

    operating_margins_tf = deps.repeat_rate(
        "Operating Margins", margin_tf, deps.projection_years
    )
    da_rates_tf = deps.repeat_rate("D&A Rates", da_rate_tf, deps.projection_years)
    capex_rates_tf = deps.repeat_rate(
        "CapEx Rates", capex_rate_tf, deps.projection_years
    )
    wc_rates_tf = deps.repeat_rate("WC Rates", wc_rate_tf, deps.projection_years)
    sbc_rates_tf = deps.repeat_rate("SBC Rates", sbc_rate_tf, deps.projection_years)

    initial_revenue = deps.value_or_missing(revenue_tf, "initial_revenue", missing)
    shares_outstanding = deps.value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = deps.value_or_missing(cash_tf, "cash", missing)
    total_debt = deps.value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = deps.value_or_missing(preferred_tf, "preferred_stock", missing)
    current_price = deps.market_float(market_snapshot, "current_price")
    (
        monte_carlo_iterations,
        monte_carlo_seed,
        monte_carlo_sampler,
    ) = deps.resolve_monte_carlo_controls(market_snapshot, assumptions)

    if growth_rates_tf.value is None:
        missing.append("growth_rates")
    if operating_margins_tf.value is None:
        missing.append("operating_margins")
    if tax_rate_tf.value is None:
        missing.append("tax_rate")
    if da_rates_tf.value is None:
        missing.append("da_rates")
    if capex_rates_tf.value is None:
        missing.append("capex_rates")
    if wc_rates_tf.value is None:
        missing.append("wc_rates")
    if sbc_rates_tf.value is None:
        missing.append("sbc_rates")

    risk_free_rate = deps.market_float(market_snapshot, "risk_free_rate")
    if risk_free_rate is None:
        risk_free_rate = DEFAULT_SAAS_RISK_FREE_RATE
        assumptions.append(
            f"risk_free_rate defaulted to {DEFAULT_SAAS_RISK_FREE_RATE:.2%}"
        )

    beta = deps.market_float(market_snapshot, "beta")
    if beta is None:
        beta = DEFAULT_SAAS_BETA
        assumptions.append(f"beta defaulted to {DEFAULT_SAAS_BETA:.2f}")

    market_risk_premium = deps.default_market_risk_premium
    assumptions.append(
        f"market_risk_premium defaulted to {deps.default_market_risk_premium:.2%}"
    )

    raw_wacc = risk_free_rate + (beta * market_risk_premium)
    clamped_wacc = _clamp(raw_wacc, WACC_FLOOR, WACC_CEILING)
    if clamped_wacc != raw_wacc:
        assumptions.append(
            f"wacc clamped from {raw_wacc:.2%} to {clamped_wacc:.2%} "
            f"(bounds={WACC_FLOOR:.2%}-{WACC_CEILING:.2%})"
        )
    else:
        assumptions.append("wacc sourced from market-aware CAPM inputs")
    wacc_tf = TraceableField(
        name="WACC",
        value=clamped_wacc,
        provenance=ManualProvenance(
            description=(
                "Market-aware CAPM-derived WACC: "
                f"risk_free_rate + beta * market_risk_premium = {raw_wacc:.4f}"
            ),
            author="ValuationPolicy",
        ),
    )

    consensus_growth_rate = deps.market_float(market_snapshot, "consensus_growth_rate")
    terminal_candidate = (
        consensus_growth_rate
        if consensus_growth_rate is not None
        else DEFAULT_TERMINAL_GROWTH
    )
    terminal_upper_bound = min(
        TERMINAL_GROWTH_CEILING,
        clamped_wacc - TERMINAL_GROWTH_SPREAD_BUFFER,
    )
    if terminal_upper_bound <= TERMINAL_GROWTH_FLOOR:
        terminal_upper_bound = TERMINAL_GROWTH_FLOOR + 0.001
    clamped_terminal_growth = _clamp(
        terminal_candidate,
        TERMINAL_GROWTH_FLOOR,
        terminal_upper_bound,
    )
    if consensus_growth_rate is None:
        assumptions.append(
            f"terminal_growth defaulted to {DEFAULT_TERMINAL_GROWTH:.2%} "
            "(consensus unavailable)"
        )
    elif clamped_terminal_growth != terminal_candidate:
        assumptions.append(
            f"terminal_growth clamped from {terminal_candidate:.2%} to "
            f"{clamped_terminal_growth:.2%} "
            f"(bounds={TERMINAL_GROWTH_FLOOR:.2%}-{terminal_upper_bound:.2%})"
        )
    else:
        assumptions.append("terminal_growth sourced from consensus_growth_rate")
    terminal_growth_tf = TraceableField(
        name="Terminal Growth",
        value=clamped_terminal_growth,
        provenance=ManualProvenance(
            description=(
                "Consensus-aware terminal growth with economic bounds "
                f"(upper=min({TERMINAL_GROWTH_CEILING:.2%}, wacc-"
                f"{TERMINAL_GROWTH_SPREAD_BUFFER:.2%}))"
            ),
            author="ValuationPolicy",
        ),
    )

    trace_inputs: dict[str, TraceInput] = {
        "initial_revenue": revenue_tf,
        "growth_rates": growth_rates_tf,
        "operating_margins": operating_margins_tf,
        "tax_rate": tax_rate_tf,
        "da_rates": da_rates_tf,
        "capex_rates": capex_rates_tf,
        "wc_rates": wc_rates_tf,
        "sbc_rates": sbc_rates_tf,
        "wacc": wacc_tf,
        "terminal_growth": terminal_growth_tf,
        "risk_free_rate": TraceableField(
            name="Risk-Free Rate",
            value=risk_free_rate,
            provenance=ManualProvenance(
                description="Market-derived risk-free rate for SaaS CAPM",
                author="MarketDataClient",
            ),
        ),
        "beta": TraceableField(
            name="Beta",
            value=beta,
            provenance=ManualProvenance(
                description="Market-derived beta for SaaS CAPM",
                author="MarketDataClient",
            ),
        ),
        "market_risk_premium": TraceableField(
            name="Market Risk Premium",
            value=market_risk_premium,
            provenance=ManualProvenance(
                description="Policy market risk premium for SaaS CAPM",
                author="ValuationPolicy",
            ),
        ),
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }

    rationale = "Derived from SEC XBRL (financial reports) with computed rates."
    if assumptions:
        rationale += " Controlled assumptions applied: " + "; ".join(assumptions)

    params: dict[str, object] = {
        "ticker": ticker or "UNKNOWN",
        "rationale": rationale,
        "initial_revenue": initial_revenue,
        "growth_rates": growth_rates_tf.value,
        "operating_margins": operating_margins_tf.value,
        "tax_rate": tax_rate_tf.value,
        "da_rates": da_rates_tf.value,
        "capex_rates": capex_rates_tf.value,
        "wc_rates": wc_rates_tf.value,
        "sbc_rates": sbc_rates_tf.value,
        "wacc": wacc_tf.value,
        "terminal_growth": terminal_growth_tf.value,
        "risk_free_rate": risk_free_rate,
        "beta": beta,
        "market_risk_premium": market_risk_premium,
        "shares_outstanding": shares_outstanding,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "current_price": current_price,
        "monte_carlo_iterations": monte_carlo_iterations,
        "monte_carlo_seed": monte_carlo_seed,
        "monte_carlo_sampler": monte_carlo_sampler,
    }

    return SaasBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )
