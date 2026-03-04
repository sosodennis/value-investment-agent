from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import ManualProvenance, TraceableField

from ....policies.manual_assumption_policy import (
    DEFAULT_DA_RATE,
    DEFAULT_TERMINAL_GROWTH,
    assume_rate,
)
from ....report_contract import FinancialReport, IndustrialExtension
from ...core_ops_service import ratio_with_optional_inputs
from ...types import MonteCarloControls, TraceInput
from ..shared.capital_structure_value_extraction_service import (
    extract_filing_capital_structure_market_values,
)
from ..shared.capm_market_defaults_service import resolve_capm_market_defaults
from ..shared.common_output_assembly_service import (
    build_base_params,
    build_capital_structure_params,
    build_capital_structure_trace_inputs,
    build_capm_market_params,
    build_capm_market_trace_inputs,
    build_monte_carlo_params,
)
from ..shared.missing_metrics_service import collect_missing_metric_names

DEFAULT_SAAS_RISK_FREE_RATE = 0.042
DEFAULT_SAAS_BETA = 1.0
BETA_FLOOR = 0.50
BETA_CEILING = 1.80
WACC_FLOOR = 0.05
WACC_CEILING = 0.30
TERMINAL_GROWTH_FLOOR = -0.02
TERMINAL_GROWTH_CEILING = 0.04
TERMINAL_GROWTH_SPREAD_BUFFER = 0.005


@dataclass(frozen=True)
class _SaasCapmTerminalInputs:
    risk_free_rate: float
    beta: float
    market_risk_premium: float
    wacc_tf: TraceableField[float]
    terminal_growth_tf: TraceableField[float]


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _to_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def _to_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return int(float(normalized))
        except ValueError:
            return None
    return None


def _extract_market_datum_staleness(
    market_snapshot: Mapping[str, object] | None,
    *,
    field: str,
) -> tuple[bool | None, int | None, int | None]:
    if market_snapshot is None:
        return None, None, None
    market_datums_raw = market_snapshot.get("market_datums")
    if not isinstance(market_datums_raw, Mapping):
        return None, None, None
    datum_raw = market_datums_raw.get(field)
    if not isinstance(datum_raw, Mapping):
        return None, None, None
    staleness_raw = datum_raw.get("staleness")
    if not isinstance(staleness_raw, Mapping):
        return None, None, None
    is_stale_raw = staleness_raw.get("is_stale")
    days_raw = staleness_raw.get("days")
    max_days_raw = staleness_raw.get("max_days")
    is_stale = is_stale_raw if isinstance(is_stale_raw, bool) else None
    stale_days = days_raw if isinstance(days_raw, int) else _to_int(days_raw)
    stale_max_days = (
        max_days_raw if isinstance(max_days_raw, int) else _to_int(max_days_raw)
    )
    return is_stale, stale_days, stale_max_days


def _derive_filing_terminal_growth_anchor(
    reports: list[FinancialReport],
) -> float | None:
    points: list[tuple[int, float]] = []
    for report in reports:
        year = _to_int(report.base.fiscal_year.value)
        revenue = _to_float(report.base.total_revenue.value)
        if year is None or revenue is None or revenue <= 0:
            continue
        points.append((year, revenue))

    if len(points) < 2:
        return None
    points.sort(key=lambda item: item[0])
    first_year, first_revenue = points[0]
    last_year, last_revenue = points[-1]
    if last_revenue <= 0 or first_revenue <= 0:
        return None

    span_years = last_year - first_year
    if span_years > 0:
        return (last_revenue / first_revenue) ** (1.0 / float(span_years)) - 1.0

    previous_revenue = points[-2][1]
    if previous_revenue <= 0:
        return None
    return (last_revenue - previous_revenue) / previous_revenue


def _build_saas_capm_terminal_inputs(
    *,
    reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
    market_float: Callable[[Mapping[str, object] | None, str], float | None],
    default_market_risk_premium: float,
    assumptions: list[str],
) -> _SaasCapmTerminalInputs:
    market_defaults = resolve_capm_market_defaults(
        market_snapshot=market_snapshot,
        market_float=market_float,
        default_risk_free_rate=DEFAULT_SAAS_RISK_FREE_RATE,
        risk_free_format=".2%",
        default_beta=DEFAULT_SAAS_BETA,
        beta_format=".2f",
        default_market_risk_premium=default_market_risk_premium,
        market_risk_premium_format=".2%",
        assumptions=assumptions,
    )
    risk_free_rate = market_defaults.risk_free_rate
    raw_beta = market_defaults.beta
    beta = _clamp(raw_beta, BETA_FLOOR, BETA_CEILING)
    if beta != raw_beta:
        assumptions.append(
            f"beta clamped from {raw_beta:.3f} to {beta:.3f} "
            f"(bounds={BETA_FLOOR:.3f}-{BETA_CEILING:.3f})"
        )
    market_risk_premium = market_defaults.market_risk_premium

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

    long_run_growth_anchor = market_float(market_snapshot, "long_run_growth_anchor")
    anchor_is_stale, anchor_stale_days, anchor_stale_max_days = (
        _extract_market_datum_staleness(
            market_snapshot,
            field="long_run_growth_anchor",
        )
    )
    anchor_source = "market"
    terminal_anchor = long_run_growth_anchor
    if anchor_is_stale is True:
        filing_anchor = _derive_filing_terminal_growth_anchor(reports)
        stale_days_label = (
            str(anchor_stale_days) if isinstance(anchor_stale_days, int) else "unknown"
        )
        stale_max_label = (
            str(anchor_stale_max_days)
            if isinstance(anchor_stale_max_days, int)
            else "unknown"
        )
        if filing_anchor is not None:
            terminal_anchor = filing_anchor
            anchor_source = "filing"
            assumptions.append(
                "terminal_growth fallback to filing-first anchor "
                "(market stale: "
                f"age_days={stale_days_label}, threshold={stale_max_label})"
            )
        else:
            assumptions.append(
                "terminal_growth stale market anchor could not fallback to filing-first "
                "(filing anchor unavailable)"
            )
            terminal_anchor = None

    if terminal_anchor is None:
        terminal_anchor = DEFAULT_TERMINAL_GROWTH
        anchor_source = "default"

    terminal_upper_bound = min(
        TERMINAL_GROWTH_CEILING,
        clamped_wacc - TERMINAL_GROWTH_SPREAD_BUFFER,
    )
    if terminal_upper_bound <= TERMINAL_GROWTH_FLOOR:
        terminal_upper_bound = TERMINAL_GROWTH_FLOOR + 0.001
    clamped_terminal_growth = _clamp(
        terminal_anchor,
        TERMINAL_GROWTH_FLOOR,
        terminal_upper_bound,
    )
    if anchor_source == "default":
        assumptions.append(
            f"terminal_growth defaulted to {DEFAULT_TERMINAL_GROWTH:.2%} "
            "(long_run_growth_anchor unavailable)"
        )
    elif clamped_terminal_growth != terminal_anchor:
        assumptions.append(
            f"terminal_growth clamped from {terminal_anchor:.2%} to "
            f"{clamped_terminal_growth:.2%} "
            f"(bounds={TERMINAL_GROWTH_FLOOR:.2%}-{terminal_upper_bound:.2%})"
        )
    elif anchor_source == "filing":
        assumptions.append(
            "terminal_growth sourced from filing-first anchor "
            "(market stale fallback)"
        )
    else:
        assumptions.append("terminal_growth sourced from long_run_growth_anchor")
    terminal_growth_tf = TraceableField(
        name="Terminal Growth",
        value=clamped_terminal_growth,
        provenance=ManualProvenance(
            description=(
                "Long-run-anchor terminal growth with economic bounds "
                f"(upper=min({TERMINAL_GROWTH_CEILING:.2%}, wacc-"
                f"{TERMINAL_GROWTH_SPREAD_BUFFER:.2%}))"
            ),
            author="ValuationPolicy",
        ),
    )

    return _SaasCapmTerminalInputs(
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        wacc_tf=wacc_tf,
        terminal_growth_tf=terminal_growth_tf,
    )


@dataclass(frozen=True)
class _SaasOperatingRates:
    margin_tf: TraceableField[float]
    tax_rate_tf: TraceableField[float]
    da_rate_tf: TraceableField[float]
    capex_rate_tf: TraceableField[float]
    sbc_rate_tf: TraceableField[float]
    wc_rate_tf: TraceableField[float]


def _build_saas_operating_rates(
    *,
    latest: FinancialReport,
    reports: list[FinancialReport],
    revenue_tf: TraceableField[float],
    ratio: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ],
    subtract: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ],
    missing_field: Callable[[str, str], TraceableField[float]],
    assumptions: list[str],
) -> _SaasOperatingRates:
    base = latest.base
    extension = (
        latest.extension if isinstance(latest.extension, IndustrialExtension) else None
    )

    operating_income_tf = base.operating_income
    tax_expense_tf = base.income_tax_expense
    income_before_tax_tf = base.income_before_tax
    da_tf = base.depreciation_and_amortization
    sbc_tf = base.share_based_compensation
    capex_tf = extension.capex if extension else None

    margin_tf = ratio(
        "Operating Margin",
        operating_income_tf,
        revenue_tf,
        "OperatingIncome / Revenue",
    )
    tax_rate_tf = ratio(
        "Tax Rate",
        tax_expense_tf,
        income_before_tax_tf,
        "IncomeTaxExpense / IncomeBeforeTax",
    )
    da_rate_tf = ratio(
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

    capex_rate_tf = ratio_with_optional_inputs(
        name="CapEx Rate",
        numerator=capex_tf,
        denominator=revenue_tf,
        expression="CapEx / Revenue",
        missing_reason="Missing CapEx for CapEx Rate",
        ratio_op=ratio,
        missing_field_op=missing_field,
    )
    sbc_rate_tf = ratio(
        "SBC Rate",
        sbc_tf,
        revenue_tf,
        "ShareBasedCompensation / Revenue",
    )

    current_assets_tf = base.current_assets
    current_liabilities_tf = base.current_liabilities
    wc_latest = subtract(
        "Working Capital (Latest)",
        current_assets_tf,
        current_liabilities_tf,
        "CurrentAssets - CurrentLiabilities",
    )
    wc_prev = None
    if len(reports) > 1:
        prev = reports[1]
        wc_prev = subtract(
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
        wc_delta = subtract(
            "Working Capital Delta",
            wc_latest,
            wc_prev,
            "WorkingCapitalLatest - WorkingCapitalPrevious",
        )
        wc_rate_tf = ratio("WC Rate", wc_delta, revenue_tf, "ChangeInWC / Revenue")
    else:
        wc_rate_tf = missing_field("WC Rate", "Missing working capital history")

    return _SaasOperatingRates(
        margin_tf=margin_tf,
        tax_rate_tf=tax_rate_tf,
        da_rate_tf=da_rate_tf,
        capex_rate_tf=capex_rate_tf,
        sbc_rate_tf=sbc_rate_tf,
        wc_rate_tf=wc_rate_tf,
    )


def _collect_saas_missing_metric_names(
    *,
    growth_rates_tf: TraceableField[list[float]],
    operating_margins_tf: TraceableField[list[float]],
    tax_rate_tf: TraceableField[float],
    da_rates_tf: TraceableField[list[float]],
    capex_rates_tf: TraceableField[list[float]],
    wc_rates_tf: TraceableField[list[float]],
    sbc_rates_tf: TraceableField[list[float]],
) -> list[str]:
    return collect_missing_metric_names(
        metric_fields={
            "growth_rates": growth_rates_tf,
            "operating_margins": operating_margins_tf,
            "tax_rate": tax_rate_tf,
            "da_rates": da_rates_tf,
            "capex_rates": capex_rates_tf,
            "wc_rates": wc_rates_tf,
            "sbc_rates": sbc_rates_tf,
        }
    )


def _build_saas_trace_inputs(
    *,
    revenue_tf: TraceableField[float],
    growth_rates_tf: TraceableField[list[float]],
    operating_margins_tf: TraceableField[list[float]],
    tax_rate_tf: TraceableField[float],
    da_rates_tf: TraceableField[list[float]],
    capex_rates_tf: TraceableField[list[float]],
    wc_rates_tf: TraceableField[list[float]],
    sbc_rates_tf: TraceableField[list[float]],
    wacc_tf: TraceableField[float],
    terminal_growth_tf: TraceableField[float],
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
    cash_tf: TraceableField[float],
    debt_tf: TraceableField[float],
    preferred_tf: TraceableField[float],
    shares_tf: TraceableField[float],
) -> dict[str, TraceInput]:
    return {
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
        **build_capm_market_trace_inputs(
            risk_free_rate=risk_free_rate,
            beta=beta,
            market_risk_premium=market_risk_premium,
            risk_free_description="Market-derived risk-free rate for SaaS CAPM",
            beta_description="Market-derived beta for SaaS CAPM",
            market_risk_premium_description="Policy market risk premium for SaaS CAPM",
        ),
        **build_capital_structure_trace_inputs(
            cash_tf=cash_tf,
            debt_tf=debt_tf,
            preferred_tf=preferred_tf,
            shares_tf=shares_tf,
        ),
    }


def _build_saas_rationale(assumptions: list[str]) -> str:
    rationale = "Derived from SEC XBRL (financial reports) with computed rates."
    if assumptions:
        rationale += " Controlled assumptions applied: " + "; ".join(assumptions)
    return rationale


def _build_saas_params(
    *,
    ticker: str | None,
    rationale: str,
    initial_revenue: float | None,
    growth_rates: list[float] | None,
    operating_margins: list[float] | None,
    tax_rate: float | None,
    da_rates: list[float] | None,
    capex_rates: list[float] | None,
    wc_rates: list[float] | None,
    sbc_rates: list[float] | None,
    wacc: float | None,
    terminal_growth: float | None,
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
    shares_outstanding: float | None,
    cash: float | None,
    total_debt: float | None,
    preferred_stock: float | None,
    current_price: float | None,
    monte_carlo_iterations: int,
    monte_carlo_seed: int | None,
    monte_carlo_sampler: str,
) -> dict[str, object]:
    return {
        **build_base_params(
            ticker=ticker,
            rationale=rationale,
        ),
        "initial_revenue": initial_revenue,
        "growth_rates": growth_rates,
        "operating_margins": operating_margins,
        "tax_rate": tax_rate,
        "da_rates": da_rates,
        "capex_rates": capex_rates,
        "wc_rates": wc_rates,
        "sbc_rates": sbc_rates,
        "wacc": wacc,
        "terminal_growth": terminal_growth,
        **build_capm_market_params(
            risk_free_rate=risk_free_rate,
            beta=beta,
            market_risk_premium=market_risk_premium,
        ),
        **build_capital_structure_params(
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
            current_price=current_price,
        ),
        **build_monte_carlo_params(
            monte_carlo_iterations=monte_carlo_iterations,
            monte_carlo_seed=monte_carlo_seed,
            monte_carlo_sampler=monte_carlo_sampler,
        ),
    }


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
        MonteCarloControls,
    ]
    missing_field: Callable[[str, str], TraceableField[float]]


@dataclass(frozen=True)
class SaasBuildPayload:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    shares_source: str


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

    revenue_tf = base.total_revenue
    shares_tf = deps.resolve_shares_outstanding(
        base.shares_outstanding,
        market_snapshot,
        assumptions,
    )
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock

    operating_rates = _build_saas_operating_rates(
        latest=latest,
        reports=reports,
        revenue_tf=revenue_tf,
        ratio=deps.ratio,
        subtract=deps.subtract,
        missing_field=deps.missing_field,
        assumptions=assumptions,
    )
    margin_tf = operating_rates.margin_tf
    tax_rate_tf = operating_rates.tax_rate_tf
    da_rate_tf = operating_rates.da_rate_tf
    capex_rate_tf = operating_rates.capex_rate_tf
    sbc_rate_tf = operating_rates.sbc_rate_tf
    wc_rate_tf = operating_rates.wc_rate_tf

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

    initial_revenue = deps.value_or_missing(
        revenue_tf,
        "initial_revenue",
        missing,
    )
    market_values = extract_filing_capital_structure_market_values(
        value_or_missing=deps.value_or_missing,
        missing=missing,
        shares_tf=shares_tf,
        cash_tf=cash_tf,
        debt_tf=debt_tf,
        preferred_tf=preferred_tf,
        market_float=deps.market_float,
        market_snapshot=market_snapshot,
    )
    shares_outstanding = market_values.shares_outstanding
    cash = market_values.cash
    total_debt = market_values.total_debt
    preferred_stock = market_values.preferred_stock
    current_price = market_values.current_price
    shares_source = market_values.shares_source
    (
        monte_carlo_iterations,
        monte_carlo_seed,
        monte_carlo_sampler,
    ) = deps.resolve_monte_carlo_controls(market_snapshot, assumptions)

    missing.extend(
        _collect_saas_missing_metric_names(
            growth_rates_tf=growth_rates_tf,
            operating_margins_tf=operating_margins_tf,
            tax_rate_tf=tax_rate_tf,
            da_rates_tf=da_rates_tf,
            capex_rates_tf=capex_rates_tf,
            wc_rates_tf=wc_rates_tf,
            sbc_rates_tf=sbc_rates_tf,
        )
    )

    capm_terminal_inputs = _build_saas_capm_terminal_inputs(
        reports=reports,
        market_snapshot=market_snapshot,
        market_float=deps.market_float,
        default_market_risk_premium=deps.default_market_risk_premium,
        assumptions=assumptions,
    )
    risk_free_rate = capm_terminal_inputs.risk_free_rate
    beta = capm_terminal_inputs.beta
    market_risk_premium = capm_terminal_inputs.market_risk_premium
    wacc_tf = capm_terminal_inputs.wacc_tf
    terminal_growth_tf = capm_terminal_inputs.terminal_growth_tf

    trace_inputs: dict[str, TraceInput] = _build_saas_trace_inputs(
        revenue_tf=revenue_tf,
        growth_rates_tf=growth_rates_tf,
        operating_margins_tf=operating_margins_tf,
        tax_rate_tf=tax_rate_tf,
        da_rates_tf=da_rates_tf,
        capex_rates_tf=capex_rates_tf,
        wc_rates_tf=wc_rates_tf,
        sbc_rates_tf=sbc_rates_tf,
        wacc_tf=wacc_tf,
        terminal_growth_tf=terminal_growth_tf,
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        cash_tf=cash_tf,
        debt_tf=debt_tf,
        preferred_tf=preferred_tf,
        shares_tf=shares_tf,
    )

    rationale = _build_saas_rationale(assumptions)
    params: dict[str, object] = _build_saas_params(
        ticker=ticker,
        rationale=rationale,
        initial_revenue=initial_revenue,
        growth_rates=growth_rates_tf.value,
        operating_margins=operating_margins_tf.value,
        tax_rate=tax_rate_tf.value,
        da_rates=da_rates_tf.value,
        capex_rates=capex_rates_tf.value,
        wc_rates=wc_rates_tf.value,
        sbc_rates=sbc_rates_tf.value,
        wacc=wacc_tf.value,
        terminal_growth=terminal_growth_tf.value,
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        shares_outstanding=shares_outstanding,
        cash=cash,
        total_debt=total_debt,
        preferred_stock=preferred_stock,
        current_price=current_price,
        monte_carlo_iterations=monte_carlo_iterations,
        monte_carlo_seed=monte_carlo_seed,
        monte_carlo_sampler=monte_carlo_sampler,
    )

    return SaasBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )
