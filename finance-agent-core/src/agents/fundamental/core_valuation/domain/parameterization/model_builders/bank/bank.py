from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.fundamental.shared.contracts.traceable import (
    ManualProvenance,
    TraceableField,
)

from ....policies.manual_assumption_policy import DEFAULT_TERMINAL_GROWTH, assume_rate
from ....report_contract import FinancialReport, FinancialServicesExtension
from ...core_ops_service import ratio_with_optional_inputs
from ...types import MonteCarloControls, TraceInput
from ..shared.capm_market_defaults_service import resolve_capm_market_defaults
from ..shared.market_value_extraction import (
    extract_required_values,
    extract_xbrl_filing_equity_market_values,
)
from ..shared.missing_metrics_service import collect_missing_metric_names
from ..shared.parameter_assembly_service import (
    build_capm_market_params,
    build_capm_market_trace_inputs,
    build_equity_value_params,
    build_monte_carlo_params,
    build_sec_xbrl_base_params,
    build_shares_trace_inputs,
    resolve_optional_trace_input,
)

DEFAULT_BANK_RISK_FREE_RATE = 0.042
DEFAULT_BANK_BETA = 1.0
DEFAULT_BANK_RORWA = 0.03


@dataclass(frozen=True)
class _BankCapmTerminalInputs:
    risk_free_rate: float
    beta: float
    market_risk_premium: float
    terminal_growth_tf: TraceableField[float]


def _build_bank_capm_terminal_inputs(
    *,
    market_snapshot: Mapping[str, object] | None,
    market_float: Callable[[Mapping[str, object] | None, str], float | None],
    default_market_risk_premium: float,
    assumptions: list[str],
) -> _BankCapmTerminalInputs:
    market_defaults = resolve_capm_market_defaults(
        market_snapshot=market_snapshot,
        market_float=market_float,
        default_risk_free_rate=DEFAULT_BANK_RISK_FREE_RATE,
        risk_free_format=".1%",
        default_beta=DEFAULT_BANK_BETA,
        beta_format=".1f",
        default_market_risk_premium=default_market_risk_premium,
        market_risk_premium_format=".2%",
        allow_market_snapshot_mrp=False,
        assumptions=assumptions,
    )

    terminal_growth_tf = assume_rate(
        "Terminal Growth",
        DEFAULT_TERMINAL_GROWTH,
        "Policy default terminal growth (preview only; requires analyst review)",
    )
    assumptions.append(f"terminal_growth defaulted to {DEFAULT_TERMINAL_GROWTH:.2%}")

    return _BankCapmTerminalInputs(
        risk_free_rate=market_defaults.risk_free_rate,
        beta=market_defaults.beta,
        market_risk_premium=market_defaults.market_risk_premium,
        terminal_growth_tf=terminal_growth_tf,
    )


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


def _build_bank_rorwa_intensity(
    *,
    reports: list[FinancialReport],
    net_income_tf: TraceableField[float],
    rwa_tf: TraceableField[float] | None,
    ratio: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ],
    missing_field: Callable[[str, str], TraceableField[float]],
    assumptions: list[str],
) -> TraceableField[float]:
    latest_rorwa_tf = ratio_with_optional_inputs(
        name="RoRWA",
        numerator=net_income_tf,
        denominator=rwa_tf,
        expression="NetIncome / RiskWeightedAssets",
        missing_reason="Missing Risk-Weighted Assets",
        ratio_op=ratio,
        missing_field_op=missing_field,
    )
    baseline_rorwa = _median(_bank_rorwa_observations(reports[1:]))
    baseline_rwa = _median(_bank_rwa_observations(reports[1:]))
    latest_rwa = _to_float(rwa_tf.value) if rwa_tf is not None else None

    if latest_rorwa_tf.value is None:
        if baseline_rorwa is not None:
            assumptions.append("rwa_intensity fallback to historical median RoRWA")
            return TraceableField(
                name="RoRWA",
                value=baseline_rorwa,
                provenance=ManualProvenance(
                    description=(
                        "Latest RoRWA unavailable; fell back to historical median RoRWA"
                    ),
                    author="ValuationPolicy",
                ),
            )
        assumptions.append(
            f"rwa_intensity defaulted to {DEFAULT_BANK_RORWA:.2%} (RoRWA)"
        )
        return TraceableField(
            name="RoRWA",
            value=DEFAULT_BANK_RORWA,
            provenance=ManualProvenance(
                description=(
                    "RoRWA unavailable; using conservative default RoRWA for bank DDM"
                ),
                author="ValuationPolicy",
            ),
        )

    latest_rorwa = float(latest_rorwa_tf.value)
    if _is_bank_rwa_discontinuous(latest_rwa or 0.0, baseline_rwa):
        if baseline_rorwa is not None:
            assumptions.append(
                "rwa_intensity fallback to historical median RoRWA "
                "(latest RWA discontinuity)"
            )
            return TraceableField(
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
            f"rwa_intensity defaulted to {DEFAULT_BANK_RORWA:.2%} "
            "(latest RWA discontinuity)"
        )
        return TraceableField(
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

    if _is_bank_rorwa_outlier(latest_rorwa, baseline_rorwa):
        if baseline_rorwa is not None:
            assumptions.append(
                "rwa_intensity fallback to historical median RoRWA (latest outlier)"
            )
            return TraceableField(
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
            f"rwa_intensity defaulted to {DEFAULT_BANK_RORWA:.2%} (RoRWA outlier)"
        )
        return TraceableField(
            name="RoRWA",
            value=DEFAULT_BANK_RORWA,
            provenance=ManualProvenance(
                description=(
                    "Latest RoRWA flagged as outlier; using conservative default RoRWA"
                ),
                author="ValuationPolicy",
            ),
        )

    return latest_rorwa_tf


def _collect_bank_missing_metric_names(
    *,
    income_growth_tf: TraceableField[list[float]],
    rwa_intensity_tf: TraceableField[float],
    tier1_tf: TraceableField[float] | None,
) -> list[str]:
    return collect_missing_metric_names(
        metric_fields={
            "income_growth_rates": income_growth_tf,
            "rwa_intensity": rwa_intensity_tf,
            "tier1_target_ratio": tier1_tf,
        }
    )


def _build_bank_trace_inputs(
    *,
    net_income_tf: TraceableField[float],
    income_growth_tf: TraceableField[list[float]],
    rwa_intensity_tf: TraceableField[float],
    tier1_tf: TraceableField[float] | None,
    total_equity_tf: TraceableField[float],
    shares_tf: TraceableField[float],
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
    terminal_growth_tf: TraceableField[float],
    missing_field: Callable[[str, str], TraceableField[float]],
) -> dict[str, TraceInput]:
    return {
        "initial_net_income": net_income_tf,
        "income_growth_rates": income_growth_tf,
        "rwa_intensity": rwa_intensity_tf,
        "tier1_target_ratio": resolve_optional_trace_input(
            trace_input=tier1_tf,
            field_name="Tier1 Target Ratio",
            missing_reason="Missing Tier 1 ratio",
            missing_field=missing_field,
        ),
        "initial_capital": total_equity_tf,
        **build_shares_trace_inputs(shares_tf=shares_tf),
        **build_capm_market_trace_inputs(
            risk_free_rate=risk_free_rate,
            beta=beta,
            market_risk_premium=market_risk_premium,
            risk_free_description="Market-derived risk-free rate for CAPM",
            beta_description="Market-derived equity beta for CAPM",
            market_risk_premium_description="Policy market risk premium for CAPM",
        ),
        "terminal_growth": terminal_growth_tf,
    }


def _build_bank_params(
    *,
    ticker: str | None,
    initial_net_income: float | None,
    income_growth_rates: list[float] | None,
    rwa_intensity: float | None,
    tier1_target_ratio: float | None,
    initial_capital: float | None,
    shares_outstanding: float | None,
    current_price: float | None,
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
    terminal_growth: float | None,
    monte_carlo_iterations: int,
    monte_carlo_seed: int | None,
    monte_carlo_sampler: str,
) -> dict[str, object]:
    return {
        **build_sec_xbrl_base_params(ticker=ticker),
        "initial_net_income": initial_net_income,
        "income_growth_rates": income_growth_rates,
        "rwa_intensity": rwa_intensity,
        "tier1_target_ratio": tier1_target_ratio,
        "initial_capital": initial_capital,
        **build_equity_value_params(
            shares_outstanding=shares_outstanding,
            current_price=current_price,
        ),
        **build_capm_market_params(
            risk_free_rate=risk_free_rate,
            beta=beta,
            market_risk_premium=market_risk_premium,
        ),
        "cost_of_equity_strategy": "capm",
        "cost_of_equity": None,
        "cost_of_equity_override": None,
        "terminal_growth": terminal_growth,
        **build_monte_carlo_params(
            monte_carlo_iterations=monte_carlo_iterations,
            monte_carlo_seed=monte_carlo_seed,
            monte_carlo_sampler=monte_carlo_sampler,
        ),
    }


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
        [Mapping[str, object] | None, list[str]], MonteCarloControls
    ]


@dataclass(frozen=True)
class BankBuildPayload:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    shares_source: str


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
    rwa_intensity_tf = _build_bank_rorwa_intensity(
        reports=reports,
        net_income_tf=net_income_tf,
        rwa_tf=rwa_tf,
        ratio=deps.ratio,
        missing_field=deps.missing_field,
        assumptions=assumptions,
    )

    extracted_values = extract_required_values(
        value_or_missing=deps.value_or_missing,
        missing=missing,
        fields={
            "initial_net_income": net_income_tf,
            "initial_capital": total_equity_tf,
        },
    )
    initial_net_income = extracted_values["initial_net_income"]
    initial_capital = extracted_values["initial_capital"]
    equity_market_values = extract_xbrl_filing_equity_market_values(
        value_or_missing=deps.value_or_missing,
        missing=missing,
        shares_tf=shares_tf,
        market_float=deps.market_float,
        market_snapshot=market_snapshot,
    )
    shares_outstanding = equity_market_values.shares_outstanding
    current_price = equity_market_values.current_price
    shares_source = equity_market_values.shares_source

    missing.extend(
        _collect_bank_missing_metric_names(
            income_growth_tf=income_growth_tf,
            rwa_intensity_tf=rwa_intensity_tf,
            tier1_tf=tier1_tf,
        )
    )

    capm_terminal_inputs = _build_bank_capm_terminal_inputs(
        market_snapshot=market_snapshot,
        market_float=deps.market_float,
        default_market_risk_premium=deps.default_market_risk_premium,
        assumptions=assumptions,
    )
    risk_free_rate = capm_terminal_inputs.risk_free_rate
    beta = capm_terminal_inputs.beta
    market_risk_premium = capm_terminal_inputs.market_risk_premium
    terminal_growth_tf = capm_terminal_inputs.terminal_growth_tf

    (
        monte_carlo_iterations,
        monte_carlo_seed,
        monte_carlo_sampler,
    ) = deps.resolve_monte_carlo_controls(
        market_snapshot,
        assumptions,
    )

    trace_inputs: dict[str, TraceInput] = _build_bank_trace_inputs(
        net_income_tf=net_income_tf,
        income_growth_tf=income_growth_tf,
        rwa_intensity_tf=rwa_intensity_tf,
        tier1_tf=tier1_tf,
        total_equity_tf=total_equity_tf,
        shares_tf=shares_tf,
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        terminal_growth_tf=terminal_growth_tf,
        missing_field=deps.missing_field,
    )

    params: dict[str, object] = _build_bank_params(
        ticker=ticker,
        initial_net_income=initial_net_income,
        income_growth_rates=income_growth_tf.value,
        rwa_intensity=rwa_intensity_tf.value,
        tier1_target_ratio=tier1_tf.value if tier1_tf is not None else None,
        initial_capital=initial_capital,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        terminal_growth=terminal_growth_tf.value,
        monte_carlo_iterations=monte_carlo_iterations,
        monte_carlo_seed=monte_carlo_seed,
        monte_carlo_sampler=monte_carlo_sampler,
    )

    return BankBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )
