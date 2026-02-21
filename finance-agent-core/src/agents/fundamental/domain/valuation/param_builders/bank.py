from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import ManualProvenance, TraceableField

from ..assumptions import DEFAULT_TERMINAL_GROWTH, assume_rate
from ..report_contract import FinancialReport, FinancialServicesExtension

TraceInput = TraceableField[float] | TraceableField[list[float]]

DEFAULT_BANK_RORWA = 0.03


@dataclass(frozen=True)
class BankBuilderDeps:
    projection_years: int
    default_market_risk_premium: float
    resolve_shares_outstanding: Callable[
        [TraceableField[float], Mapping[str, object] | None, list[str]],
        TraceableField[float],
    ]
    growth_rates_from_series: Callable[
        [str, list[TraceableField[float]], int], TraceableField[list[float]]
    ]
    ratio: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ]
    value_or_missing: Callable[
        [TraceableField[float] | None, str, list[str]], float | None
    ]
    missing_field: Callable[[str, str], TraceableField[float]]
    market_float: Callable[[Mapping[str, object] | None, str], float | None]
    resolve_monte_carlo_controls: Callable[
        [Mapping[str, object] | None, list[str]], tuple[int, int | None]
    ]


@dataclass(frozen=True)
class BankBuildPayload:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    shares_source: str


def _to_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _bank_rorwa_observations(reports: list[FinancialReport]) -> list[float]:
    observations: list[float] = []
    for report in reports:
        extension = (
            report.extension
            if isinstance(report.extension, FinancialServicesExtension)
            else None
        )
        if extension is None:
            continue
        net_income = _to_float(report.base.net_income.value)
        rwa = _to_float(extension.risk_weighted_assets.value)
        if net_income is None or rwa in (None, 0):
            continue
        value = net_income / rwa
        if value > 0:
            observations.append(float(value))
    return observations


def _bank_rwa_observations(reports: list[FinancialReport]) -> list[float]:
    observations: list[float] = []
    for report in reports:
        extension = (
            report.extension
            if isinstance(report.extension, FinancialServicesExtension)
            else None
        )
        if extension is None:
            continue
        rwa = _to_float(extension.risk_weighted_assets.value)
        if rwa is None or rwa <= 0:
            continue
        observations.append(float(rwa))
    return observations


def _is_bank_rorwa_outlier(value: float, baseline: float | None) -> bool:
    # Typical bank return-on-RWA range is low single-digit %. Extreme values
    # usually indicate tag/context mismatch rather than real economics.
    if value <= 0 or value > 0.20:
        return True
    if baseline is None or baseline <= 0:
        return False
    return value > baseline * 3.0 or value < baseline / 3.0


def _is_bank_rwa_discontinuous(value: float, baseline: float | None) -> bool:
    if value <= 0:
        return True
    if baseline is None or baseline <= 0:
        return False
    return value > baseline * 3.0 or value < baseline / 3.0


def build_bank_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
    deps: BankBuilderDeps,
) -> BankBuildPayload:
    missing: list[str] = []
    assumptions: list[str] = []

    base = latest.base
    extension = (
        latest.extension
        if isinstance(latest.extension, FinancialServicesExtension)
        else None
    )

    net_income_tf = base.net_income
    total_equity_tf = base.total_equity
    shares_tf = deps.resolve_shares_outstanding(
        base.shares_outstanding,
        market_snapshot,
        assumptions,
    )
    rwa_tf = extension.risk_weighted_assets if extension else None
    tier1_tf = extension.tier1_capital_ratio if extension else None

    income_series = [report.base.net_income for report in reports]
    income_growth_tf = deps.growth_rates_from_series(
        "Net Income Growth Rates",
        income_series,
        deps.projection_years,
    )

    latest_rorwa_tf = (
        deps.ratio(
            "RoRWA",
            net_income_tf,
            rwa_tf,
            "NetIncome / RiskWeightedAssets",
        )
        if rwa_tf is not None
        else deps.missing_field("RoRWA", "Missing Risk-Weighted Assets")
    )
    baseline_rorwa = _median(_bank_rorwa_observations(reports[1:]))
    baseline_rwa = _median(_bank_rwa_observations(reports[1:]))
    latest_rwa = _to_float(rwa_tf.value) if rwa_tf is not None else None

    if latest_rorwa_tf.value is None:
        if baseline_rorwa is not None:
            rwa_intensity_tf = TraceableField(
                name="RoRWA",
                value=baseline_rorwa,
                provenance=ManualProvenance(
                    description=(
                        "Latest RoRWA unavailable; fell back to historical median RoRWA"
                    ),
                    author="ValuationPolicy",
                ),
            )
            assumptions.append("rwa_intensity fallback to historical median RoRWA")
        else:
            rwa_intensity_tf = TraceableField(
                name="RoRWA",
                value=DEFAULT_BANK_RORWA,
                provenance=ManualProvenance(
                    description=(
                        "RoRWA unavailable; using conservative default RoRWA for bank DDM"
                    ),
                    author="ValuationPolicy",
                ),
            )
            assumptions.append(
                f"rwa_intensity defaulted to {DEFAULT_BANK_RORWA:.2%} (RoRWA)"
            )
    else:
        latest_rorwa = float(latest_rorwa_tf.value)
        if _is_bank_rwa_discontinuous(latest_rwa or 0.0, baseline_rwa):
            if baseline_rorwa is not None:
                rwa_intensity_tf = TraceableField(
                    name="RoRWA",
                    value=baseline_rorwa,
                    provenance=ManualProvenance(
                        description=(
                            "Latest Risk-Weighted Assets flagged as discontinuous; "
                            "using historical median RoRWA"
                        ),
                        author="ValuationPolicy",
                    ),
                )
                assumptions.append(
                    "rwa_intensity fallback to historical median RoRWA "
                    "(latest RWA discontinuity)"
                )
            else:
                rwa_intensity_tf = TraceableField(
                    name="RoRWA",
                    value=DEFAULT_BANK_RORWA,
                    provenance=ManualProvenance(
                        description=(
                            "Latest Risk-Weighted Assets flagged as discontinuous; "
                            "using conservative default RoRWA"
                        ),
                        author="ValuationPolicy",
                    ),
                )
                assumptions.append(
                    f"rwa_intensity defaulted to {DEFAULT_BANK_RORWA:.2%} "
                    "(latest RWA discontinuity)"
                )
        elif _is_bank_rorwa_outlier(latest_rorwa, baseline_rorwa):
            if baseline_rorwa is not None:
                rwa_intensity_tf = TraceableField(
                    name="RoRWA",
                    value=baseline_rorwa,
                    provenance=ManualProvenance(
                        description=(
                            "Latest RoRWA flagged as outlier; using historical median RoRWA"
                        ),
                        author="ValuationPolicy",
                    ),
                )
                assumptions.append(
                    "rwa_intensity fallback to historical median RoRWA (latest outlier)"
                )
            else:
                rwa_intensity_tf = TraceableField(
                    name="RoRWA",
                    value=DEFAULT_BANK_RORWA,
                    provenance=ManualProvenance(
                        description=(
                            "Latest RoRWA flagged as outlier; using conservative default RoRWA"
                        ),
                        author="ValuationPolicy",
                    ),
                )
                assumptions.append(
                    f"rwa_intensity defaulted to {DEFAULT_BANK_RORWA:.2%} (RoRWA outlier)"
                )
        else:
            rwa_intensity_tf = latest_rorwa_tf

    initial_net_income = deps.value_or_missing(
        net_income_tf,
        "initial_net_income",
        missing,
    )
    initial_capital = deps.value_or_missing(
        total_equity_tf,
        "initial_capital",
        missing,
    )
    shares_outstanding = deps.value_or_missing(
        shares_tf,
        "shares_outstanding",
        missing,
    )

    if income_growth_tf.value is None:
        missing.append("income_growth_rates")
    if rwa_intensity_tf.value is None:
        missing.append("rwa_intensity")
    if tier1_tf is None or tier1_tf.value is None:
        missing.append("tier1_target_ratio")

    current_price = deps.market_float(market_snapshot, "current_price")
    risk_free_rate = deps.market_float(market_snapshot, "risk_free_rate")
    if risk_free_rate is None:
        risk_free_rate = 0.042
        assumptions.append("risk_free_rate defaulted to 4.2%")

    beta = deps.market_float(market_snapshot, "beta")
    if beta is None:
        beta = 1.0
        assumptions.append("beta defaulted to 1.0")

    market_risk_premium = deps.default_market_risk_premium
    assumptions.append(
        f"market_risk_premium defaulted to {deps.default_market_risk_premium:.2%}"
    )

    terminal_growth_tf = assume_rate(
        "Terminal Growth",
        DEFAULT_TERMINAL_GROWTH,
        "Policy default terminal growth (preview only; requires analyst review)",
    )
    assumptions.append(f"terminal_growth defaulted to {DEFAULT_TERMINAL_GROWTH:.2%}")

    monte_carlo_iterations, monte_carlo_seed = deps.resolve_monte_carlo_controls(
        market_snapshot,
        assumptions,
    )
    shares_source = (
        "market_data"
        if "shares_outstanding sourced from market data" in assumptions
        else "xbrl_filing"
    )

    trace_inputs: dict[str, TraceInput] = {
        "initial_net_income": net_income_tf,
        "income_growth_rates": income_growth_tf,
        "rwa_intensity": rwa_intensity_tf,
        "tier1_target_ratio": tier1_tf
        if tier1_tf is not None
        else deps.missing_field("Tier1 Target Ratio", "Missing Tier 1 ratio"),
        "initial_capital": total_equity_tf,
        "shares_outstanding": shares_tf,
        "risk_free_rate": TraceableField(
            name="Risk-Free Rate",
            value=risk_free_rate,
            provenance=ManualProvenance(
                description="Market-derived risk-free rate for CAPM",
                author="MarketDataClient",
            ),
        ),
        "beta": TraceableField(
            name="Beta",
            value=beta,
            provenance=ManualProvenance(
                description="Market-derived equity beta for CAPM",
                author="MarketDataClient",
            ),
        ),
        "market_risk_premium": TraceableField(
            name="Market Risk Premium",
            value=market_risk_premium,
            provenance=ManualProvenance(
                description="Policy market risk premium for CAPM",
                author="ValuationPolicy",
            ),
        ),
        "terminal_growth": terminal_growth_tf,
    }

    params: dict[str, object] = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "initial_net_income": initial_net_income,
        "income_growth_rates": income_growth_tf.value,
        "rwa_intensity": rwa_intensity_tf.value,
        "tier1_target_ratio": tier1_tf.value if tier1_tf is not None else None,
        "initial_capital": initial_capital,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
        "risk_free_rate": risk_free_rate,
        "beta": beta,
        "market_risk_premium": market_risk_premium,
        "cost_of_equity_strategy": "capm",
        "cost_of_equity": None,
        "cost_of_equity_override": None,
        "terminal_growth": terminal_growth_tf.value,
        "monte_carlo_iterations": monte_carlo_iterations,
        "monte_carlo_seed": monte_carlo_seed,
    }

    return BankBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )
