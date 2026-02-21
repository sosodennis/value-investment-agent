from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from math import sqrt

from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
)
from src.shared.kernel.types import JSONObject

from .assumptions import (
    DEFAULT_DA_RATE,
    DEFAULT_HIGH_GROWTH_TRIGGER,
    DEFAULT_LONG_RUN_GROWTH_TARGET,
    DEFAULT_TERMINAL_GROWTH,
    DEFAULT_WACC,
    assume_rate,
    blend_growth_rate,
    project_growth_rate_series,
)
from .report_contract import (
    FinancialReport,
    FinancialServicesExtension,
    IndustrialExtension,
    RealEstateExtension,
    parse_financial_reports,
)

TraceInput = TraceableField[float] | TraceableField[list[float]]
logger = get_logger(__name__)


@dataclass(frozen=True)
class ParamBuildResult:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    metadata: JSONObject = field(default_factory=dict)


PROJECTION_YEARS = 5
DEFAULT_MARKET_RISK_PREMIUM = 0.05
DEFAULT_MAINTENANCE_CAPEX_RATIO = 0.8
DEFAULT_MONTE_CARLO_ITERATIONS = 300
DEFAULT_MONTE_CARLO_SEED = 42


def build_params(
    model_type: str,
    ticker: str | None,
    reports_raw: list[FinancialReport | dict[str, object]] | None,
    market_snapshot: Mapping[str, object] | None = None,
) -> ParamBuildResult:
    log_event(
        logger,
        event="valuation_params_build_started",
        message="valuation parameter build started",
        fields={
            "model_type": model_type,
            "ticker": ticker,
            "input_reports_count": len(reports_raw or []),
        },
    )
    reports = parse_financial_reports(reports_raw or [])
    if not reports:
        log_event(
            logger,
            event="valuation_params_build_failed",
            message="valuation parameter build failed due to missing reports",
            fields={"model_type": model_type, "ticker": ticker},
        )
        raise ValueError("No SEC XBRL financial reports available")

    reports_sorted = sorted(reports, key=_report_year, reverse=True)
    latest = reports_sorted[0]

    if model_type == "saas":
        result = _build_saas_params(
            ticker, latest, reports_sorted, market_snapshot=market_snapshot
        )
    elif model_type == "bank":
        result = _build_bank_params(
            ticker, latest, reports_sorted, market_snapshot=market_snapshot
        )
    elif model_type == "ev_revenue":
        result = _build_ev_revenue_params(
            ticker, latest, market_snapshot=market_snapshot
        )
    elif model_type == "ev_ebitda":
        result = _build_ev_ebitda_params(
            ticker, latest, market_snapshot=market_snapshot
        )
    elif model_type == "reit_ffo":
        result = _build_reit_ffo_params(ticker, latest, market_snapshot=market_snapshot)
    elif model_type == "residual_income":
        result = _build_residual_income_params(
            ticker, latest, market_snapshot=market_snapshot
        )
    elif model_type == "eva":
        result = _build_eva_params(ticker, latest, market_snapshot=market_snapshot)
    else:
        log_event(
            logger,
            event="valuation_params_build_failed",
            message="valuation parameter build failed due to unsupported model",
            fields={"model_type": model_type, "ticker": ticker},
        )
        raise ValueError(f"Unsupported model type for SEC XBRL builder: {model_type}")

    log_event(
        logger,
        event="valuation_params_build_completed",
        message="valuation parameter build completed",
        fields={
            "model_type": model_type,
            "ticker": ticker,
            "missing_count": len(result.missing),
            "assumptions_count": len(result.assumptions),
            "trace_input_count": len(result.trace_inputs),
        },
    )
    return result


def _report_year(report: FinancialReport) -> int:
    value = report.base.fiscal_year.value
    if value is None:
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _missing_field(name: str, reason: str) -> TraceableField[float]:
    return TraceableField(
        name=name,
        value=None,
        provenance=ManualProvenance(description=reason),
    )


def _computed_field(
    name: str,
    value: float | list[float],
    op_code: str,
    expression: str,
    inputs: dict[str, TraceableField],
) -> TraceableField:
    return TraceableField(
        name=name,
        value=value,
        provenance=ComputedProvenance(
            op_code=op_code,
            expression=expression,
            inputs=inputs,
        ),
    )


def _ratio(
    name: str,
    numerator: TraceableField[float],
    denominator: TraceableField[float],
    expression: str,
) -> TraceableField[float]:
    if numerator.value is None or denominator.value in (None, 0):
        return _missing_field(name, f"Missing or zero denominator for {expression}")
    value = float(numerator.value) / float(denominator.value)
    return _computed_field(
        name=name,
        value=value,
        op_code="DIV",
        expression=expression,
        inputs={numerator.name: numerator, denominator.name: denominator},
    )


def _subtract(
    name: str,
    left: TraceableField[float],
    right: TraceableField[float],
    expression: str,
) -> TraceableField[float]:
    if left.value is None or right.value is None:
        return _missing_field(name, f"Missing inputs for {expression}")
    value = float(left.value) - float(right.value)
    return _computed_field(
        name=name,
        value=value,
        op_code="SUB",
        expression=expression,
        inputs={left.name: left, right.name: right},
    )


def _repeat_rate(
    name: str, rate: TraceableField[float], count: int
) -> TraceableField[list[float]]:
    if rate.value is None:
        return TraceableField(
            name=name,
            value=None,
            provenance=ManualProvenance(description=f"Missing base rate for {name}"),
        )
    values = [float(rate.value)] * count
    return _computed_field(
        name=name,
        value=values,
        op_code="REPEAT",
        expression=f"Repeat {rate.name} for {count} years",
        inputs={rate.name: rate},
    )


def _growth_rates_from_series(
    name: str,
    series: list[TraceableField[float]],
    count: int,
) -> TraceableField[list[float]]:
    values: list[float] = []
    inputs: dict[str, TraceableField] = {}

    for idx in range(len(series) - 1):
        current = series[idx]
        previous = series[idx + 1]
        inputs[f"{current.name} (t-{idx})"] = current
        inputs[f"{previous.name} (t-{idx + 1})"] = previous
        if current.value is None or previous.value in (None, 0):
            continue
        values.append(float(current.value) / float(previous.value) - 1.0)

    if not values:
        return TraceableField(
            name=name,
            value=None,
            provenance=ManualProvenance(description="Insufficient history for growth"),
        )

    avg_growth = sum(values) / len(values)
    projected = [avg_growth] * count
    return _computed_field(
        name=name,
        value=projected,
        op_code="YOY_GROWTH_AVG",
        expression="Average historical YoY growth (SEC XBRL)",
        inputs=inputs,
    )


def _growth_observations_from_series(
    series: list[TraceableField[float]],
) -> list[float]:
    values: list[float] = []
    for idx in range(len(series) - 1):
        current = series[idx]
        previous = series[idx + 1]
        if current.value is None or previous.value in (None, 0):
            continue
        values.append(float(current.value) / float(previous.value) - 1.0)
    return values


def _stddev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return sqrt(variance)


def _value_or_missing(
    tf: TraceableField[float] | None,
    field_name: str,
    missing: list[str],
) -> float | None:
    if tf is None or tf.value is None:
        missing.append(field_name)
        return None
    return float(tf.value)


def _dedupe_missing(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


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


def _market_float(
    market_snapshot: Mapping[str, object] | None,
    key: str,
) -> float | None:
    if market_snapshot is None:
        return None
    return _to_float(market_snapshot.get(key))


def _market_text(
    market_snapshot: Mapping[str, object] | None,
    key: str,
) -> str | None:
    if market_snapshot is None:
        return None
    value = market_snapshot.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _market_text_list(
    market_snapshot: Mapping[str, object] | None,
    key: str,
) -> list[str]:
    if market_snapshot is None:
        return []
    raw = market_snapshot.get(key)
    if not isinstance(raw, list | tuple):
        return []

    output: list[str] = []
    for item in raw:
        if isinstance(item, str) and item:
            output.append(item)
    return output


def _to_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _to_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    parsed = _to_bool(value)
    if parsed is None:
        return default
    return parsed


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    value = os.getenv(name)
    parsed = _to_int(value)
    if parsed is None:
        parsed = default
    if minimum is not None and parsed < minimum:
        return minimum
    return parsed


def _resolve_monte_carlo_controls(
    *,
    market_snapshot: Mapping[str, object] | None,
    assumptions: list[str],
) -> tuple[int, int | None]:
    enabled = _env_bool("FUNDAMENTAL_MONTE_CARLO_ENABLED", True)
    iterations = _env_int(
        "FUNDAMENTAL_MONTE_CARLO_ITERATIONS",
        DEFAULT_MONTE_CARLO_ITERATIONS,
        minimum=0,
    )
    seed = _env_int(
        "FUNDAMENTAL_MONTE_CARLO_SEED",
        DEFAULT_MONTE_CARLO_SEED,
        minimum=0,
    )

    if market_snapshot is not None:
        snapshot_enabled = _to_bool(market_snapshot.get("monte_carlo_enabled"))
        snapshot_iterations = _to_int(market_snapshot.get("monte_carlo_iterations"))
        snapshot_seed = _to_int(market_snapshot.get("monte_carlo_seed"))
        if snapshot_enabled is not None:
            enabled = snapshot_enabled
        if snapshot_iterations is not None and snapshot_iterations >= 0:
            iterations = snapshot_iterations
        if snapshot_seed is not None and snapshot_seed >= 0:
            seed = snapshot_seed

    if not enabled:
        assumptions.append("monte_carlo disabled by policy")
        return 0, seed

    if iterations <= 0:
        assumptions.append("monte_carlo disabled (iterations <= 0)")
        return 0, seed

    assumptions.append(
        f"monte_carlo enabled with iterations={iterations}"
        + (f", seed={seed}" if seed is not None else "")
    )
    return iterations, seed


def _build_result_metadata(
    *,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
    shares_source: str | None = None,
) -> JSONObject:
    fiscal_year = _to_int(latest.base.fiscal_year.value)
    period_end_raw = latest.base.period_end_date.value
    period_end = (
        str(period_end_raw)
        if isinstance(period_end_raw, str | int | float) and period_end_raw is not None
        else None
    )
    provider = _market_text(market_snapshot, "provider")
    as_of = _market_text(market_snapshot, "as_of")
    missing_fields = _market_text_list(market_snapshot, "missing_fields")

    financial_statement: JSONObject = {}
    if fiscal_year is not None:
        financial_statement["fiscal_year"] = fiscal_year
    if period_end is not None:
        financial_statement["period_end_date"] = period_end

    market_data: JSONObject = {}
    if provider is not None:
        market_data["provider"] = provider
    if as_of is not None:
        market_data["as_of"] = as_of
    if missing_fields:
        market_data["missing_fields"] = missing_fields

    data_freshness: JSONObject = {}
    if financial_statement:
        data_freshness["financial_statement"] = financial_statement
    if market_data:
        data_freshness["market_data"] = market_data
    if shares_source is not None:
        data_freshness["shares_outstanding_source"] = shares_source

    if not data_freshness:
        return {}
    return {"data_freshness": data_freshness}


def _resolve_shares_outstanding(
    *,
    filing_shares_tf: TraceableField[float],
    market_snapshot: Mapping[str, object] | None,
    assumptions: list[str],
) -> TraceableField[float]:
    market_shares = _market_float(market_snapshot, "shares_outstanding")
    if market_shares is None or market_shares <= 0:
        return filing_shares_tf

    provider_raw = None if market_snapshot is None else market_snapshot.get("provider")
    as_of_raw = None if market_snapshot is None else market_snapshot.get("as_of")
    provider = str(provider_raw) if isinstance(provider_raw, str) else "market_data"
    as_of = str(as_of_raw) if isinstance(as_of_raw, str) else "unknown"

    assumptions.append("shares_outstanding sourced from market data")
    return TraceableField(
        name="Shares Outstanding (Market)",
        value=market_shares,
        provenance=ManualProvenance(
            description=(
                "Latest shares outstanding from market data "
                f"(provider={provider}, as_of={as_of})"
            ),
            author="MarketDataClient",
        ),
    )


def _build_saas_growth_rates(
    *,
    revenue_series: list[TraceableField[float]],
    market_snapshot: Mapping[str, object] | None,
    assumptions: list[str],
) -> TraceableField[list[float]]:
    historical_growth_tf = _growth_rates_from_series(
        "Revenue Growth Rates (Historical Baseline)",
        revenue_series,
        PROJECTION_YEARS,
    )

    historical_growth = None
    if historical_growth_tf.value:
        historical_growth = float(historical_growth_tf.value[0])

    historical_observations = _growth_observations_from_series(revenue_series)
    historical_volatility = _stddev(historical_observations)
    consensus_growth = _market_float(market_snapshot, "consensus_growth_rate")

    blend_result = blend_growth_rate(
        historical_growth=historical_growth,
        consensus_growth=consensus_growth,
        historical_volatility=historical_volatility,
    )
    if blend_result is None:
        return historical_growth_tf

    blended_series = project_growth_rate_series(
        base_growth=blend_result.blended_growth,
        projection_years=PROJECTION_YEARS,
        long_run_target=DEFAULT_LONG_RUN_GROWTH_TARGET,
        high_growth_trigger=DEFAULT_HIGH_GROWTH_TRIGGER,
    )

    blend_inputs: dict[str, TraceableField] = {}
    if historical_growth_tf.value is not None:
        blend_inputs["historical_growth"] = historical_growth_tf
    if consensus_growth is not None:
        provider_raw = (
            None if market_snapshot is None else market_snapshot.get("provider")
        )
        provider = provider_raw if isinstance(provider_raw, str) else "market_data"
        consensus_tf = TraceableField(
            name="Consensus Revenue Growth",
            value=consensus_growth,
            provenance=ManualProvenance(
                description=f"Consensus growth from market data provider={provider}",
                author="MarketDataClient",
            ),
        )
        blend_inputs["consensus_growth"] = consensus_tf

    assumptions.append(
        "growth_rates blended via context-aware weights "
        f"(profile={blend_result.weights.profile})"
    )

    return _computed_field(
        name="Revenue Growth Rates",
        value=blended_series,
        op_code="GROWTH_BLEND",
        expression=blend_result.rationale,
        inputs=blend_inputs,
    )


def _build_saas_params(
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    *,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base
    extension = (
        latest.extension if isinstance(latest.extension, IndustrialExtension) else None
    )

    revenue_tf = base.total_revenue
    shares_tf = _resolve_shares_outstanding(
        filing_shares_tf=base.shares_outstanding,
        market_snapshot=market_snapshot,
        assumptions=assumptions,
    )
    market_shares = _market_float(market_snapshot, "shares_outstanding")
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

    margin_tf = _ratio(
        "Operating Margin",
        operating_income_tf,
        revenue_tf,
        "OperatingIncome / Revenue",
    )
    tax_rate_tf = _ratio(
        "Tax Rate",
        tax_expense_tf,
        income_before_tax_tf,
        "IncomeTaxExpense / IncomeBeforeTax",
    )
    da_rate_tf = _ratio(
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
        _ratio("CapEx Rate", capex_tf, revenue_tf, "CapEx / Revenue")
        if capex_tf is not None
        else _missing_field("CapEx Rate", "Missing CapEx for CapEx Rate")
    )
    sbc_rate_tf = _ratio(
        "SBC Rate",
        sbc_tf,
        revenue_tf,
        "ShareBasedCompensation / Revenue",
    )

    wc_latest = _subtract(
        "Working Capital (Latest)",
        current_assets_tf,
        current_liabilities_tf,
        "CurrentAssets - CurrentLiabilities",
    )
    wc_prev = None
    if len(reports) > 1:
        prev = reports[1]
        wc_prev = _subtract(
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
        wc_delta = _subtract(
            "Working Capital Delta",
            wc_latest,
            wc_prev,
            "WorkingCapitalLatest - WorkingCapitalPrevious",
        )
        wc_rate_tf = _ratio(
            "WC Rate",
            wc_delta,
            revenue_tf,
            "ChangeInWC / Revenue",
        )
    else:
        wc_rate_tf = _missing_field("WC Rate", "Missing working capital history")

    revenue_series = [r.base.total_revenue for r in reports]
    growth_rates_tf = _build_saas_growth_rates(
        revenue_series=revenue_series,
        market_snapshot=market_snapshot,
        assumptions=assumptions,
    )

    operating_margins_tf = _repeat_rate(
        "Operating Margins", margin_tf, PROJECTION_YEARS
    )
    da_rates_tf = _repeat_rate("D&A Rates", da_rate_tf, PROJECTION_YEARS)
    capex_rates_tf = _repeat_rate("CapEx Rates", capex_rate_tf, PROJECTION_YEARS)
    wc_rates_tf = _repeat_rate("WC Rates", wc_rate_tf, PROJECTION_YEARS)
    sbc_rates_tf = _repeat_rate("SBC Rates", sbc_rate_tf, PROJECTION_YEARS)

    initial_revenue = _value_or_missing(revenue_tf, "initial_revenue", missing)
    shares_outstanding = _value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = _value_or_missing(cash_tf, "cash", missing)
    total_debt = _value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = _value_or_missing(preferred_tf, "preferred_stock", missing)
    current_price = _market_float(market_snapshot, "current_price")
    monte_carlo_iterations, monte_carlo_seed = _resolve_monte_carlo_controls(
        market_snapshot=market_snapshot,
        assumptions=assumptions,
    )

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

    # Enterprise-grade note: defaults are only for preview; require analyst review in production.
    wacc_tf = assume_rate(
        "WACC",
        DEFAULT_WACC,
        "Policy default WACC (preview only; requires analyst review)",
    )
    terminal_growth_tf = assume_rate(
        "Terminal Growth",
        DEFAULT_TERMINAL_GROWTH,
        "Policy default terminal growth (preview only; requires analyst review)",
    )
    assumptions.append(f"wacc defaulted to {DEFAULT_WACC:.2%}")
    assumptions.append(f"terminal_growth defaulted to {DEFAULT_TERMINAL_GROWTH:.2%}")

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
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }

    rationale = "Derived from SEC XBRL (financial reports) with computed rates."
    if assumptions:
        rationale += " Controlled assumptions applied: " + "; ".join(assumptions)

    params = {
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
        "shares_outstanding": shares_outstanding,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "current_price": current_price,
        "monte_carlo_iterations": monte_carlo_iterations,
        "monte_carlo_seed": monte_carlo_seed,
    }

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=shares_source,
        ),
    )


def _build_ev_revenue_params(
    ticker: str | None,
    latest: FinancialReport,
    *,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    revenue_tf = base.total_revenue
    shares_tf = _resolve_shares_outstanding(
        filing_shares_tf=base.shares_outstanding,
        market_snapshot=market_snapshot,
        assumptions=assumptions,
    )
    market_shares = _market_float(market_snapshot, "shares_outstanding")
    shares_source = (
        "market_data" if market_shares is not None and market_shares > 0 else "filing"
    )
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock

    revenue = _value_or_missing(revenue_tf, "revenue", missing)
    shares_outstanding = _value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = _value_or_missing(cash_tf, "cash", missing)
    total_debt = _value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = _value_or_missing(preferred_tf, "preferred_stock", missing)
    current_price = _market_float(market_snapshot, "current_price")

    missing.append("ev_revenue_multiple")

    trace_inputs: dict[str, TraceInput] = {
        "target_metric": revenue_tf,
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }

    params = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "revenue": revenue,
        "ev_revenue_multiple": None,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
    }

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=shares_source,
        ),
    )


def _build_ev_ebitda_params(
    ticker: str | None,
    latest: FinancialReport,
    *,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    ebitda_tf = base.ebitda
    shares_tf = _resolve_shares_outstanding(
        filing_shares_tf=base.shares_outstanding,
        market_snapshot=market_snapshot,
        assumptions=assumptions,
    )
    market_shares = _market_float(market_snapshot, "shares_outstanding")
    shares_source = (
        "market_data" if market_shares is not None and market_shares > 0 else "filing"
    )
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock

    ebitda = _value_or_missing(ebitda_tf, "ebitda", missing)
    shares_outstanding = _value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = _value_or_missing(cash_tf, "cash", missing)
    total_debt = _value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = _value_or_missing(preferred_tf, "preferred_stock", missing)
    current_price = _market_float(market_snapshot, "current_price")

    missing.append("ev_ebitda_multiple")

    trace_inputs: dict[str, TraceInput] = {
        "target_metric": ebitda_tf,
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }

    params = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "ebitda": ebitda,
        "ev_ebitda_multiple": None,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
    }

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=shares_source,
        ),
    )


def _build_reit_ffo_params(
    ticker: str | None,
    latest: FinancialReport,
    *,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base
    extension = (
        latest.extension if isinstance(latest.extension, RealEstateExtension) else None
    )

    ffo_tf = extension.ffo if extension else None
    shares_tf = _resolve_shares_outstanding(
        filing_shares_tf=base.shares_outstanding,
        market_snapshot=market_snapshot,
        assumptions=assumptions,
    )
    market_shares = _market_float(market_snapshot, "shares_outstanding")
    shares_source = (
        "market_data" if market_shares is not None and market_shares > 0 else "filing"
    )
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock
    depreciation_tf = base.depreciation_and_amortization

    ffo = _value_or_missing(ffo_tf, "ffo", missing)
    shares_outstanding = _value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = _value_or_missing(cash_tf, "cash", missing)
    total_debt = _value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = _value_or_missing(preferred_tf, "preferred_stock", missing)
    current_price = _market_float(market_snapshot, "current_price")
    monte_carlo_iterations, monte_carlo_seed = _resolve_monte_carlo_controls(
        market_snapshot=market_snapshot,
        assumptions=assumptions,
    )
    depreciation_and_amortization = _to_float(depreciation_tf.value)
    if depreciation_and_amortization is None:
        depreciation_and_amortization = 0.0
        assumptions.append("depreciation_and_amortization defaulted to 0.0 for AFFO")

    maintenance_capex_ratio = _market_float(market_snapshot, "maintenance_capex_ratio")
    if maintenance_capex_ratio is None:
        maintenance_capex_ratio = DEFAULT_MAINTENANCE_CAPEX_RATIO
        assumptions.append(
            "maintenance_capex_ratio defaulted to "
            f"{DEFAULT_MAINTENANCE_CAPEX_RATIO:.2f}"
        )

    missing.append("ffo_multiple")

    trace_inputs: dict[str, TraceInput] = {
        "ffo": ffo_tf if ffo_tf is not None else _missing_field("FFO", "Missing FFO"),
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

    params = {
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

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=shares_source,
        ),
    )


def _build_bank_params(
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    *,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
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
    rwa_tf = extension.risk_weighted_assets if extension else None
    tier1_tf = extension.tier1_capital_ratio if extension else None

    income_series = [r.base.net_income for r in reports]
    income_growth_tf = _growth_rates_from_series(
        "Net Income Growth Rates", income_series, PROJECTION_YEARS
    )

    rwa_intensity_tf = (
        _ratio(
            "RWA Intensity",
            rwa_tf,
            base.total_assets,
            "RiskWeightedAssets / TotalAssets",
        )
        if rwa_tf is not None
        else _missing_field("RWA Intensity", "Missing Risk-Weighted Assets")
    )

    initial_net_income = _value_or_missing(net_income_tf, "initial_net_income", missing)
    initial_capital = _value_or_missing(total_equity_tf, "initial_capital", missing)

    if income_growth_tf.value is None:
        missing.append("income_growth_rates")
    if rwa_intensity_tf.value is None:
        missing.append("rwa_intensity")
    if tier1_tf is None or tier1_tf.value is None:
        missing.append("tier1_target_ratio")

    risk_free_rate = _market_float(market_snapshot, "risk_free_rate")
    if risk_free_rate is None:
        risk_free_rate = 0.042
        assumptions.append("risk_free_rate defaulted to 4.2%")

    beta = _market_float(market_snapshot, "beta")
    if beta is None:
        beta = 1.0
        assumptions.append("beta defaulted to 1.0")

    market_risk_premium = DEFAULT_MARKET_RISK_PREMIUM
    assumptions.append(
        f"market_risk_premium defaulted to {DEFAULT_MARKET_RISK_PREMIUM:.2%}"
    )

    terminal_growth_tf = assume_rate(
        "Terminal Growth",
        DEFAULT_TERMINAL_GROWTH,
        "Policy default terminal growth (preview only; requires analyst review)",
    )
    assumptions.append(f"terminal_growth defaulted to {DEFAULT_TERMINAL_GROWTH:.2%}")
    monte_carlo_iterations, monte_carlo_seed = _resolve_monte_carlo_controls(
        market_snapshot=market_snapshot,
        assumptions=assumptions,
    )

    trace_inputs: dict[str, TraceInput] = {
        "initial_net_income": net_income_tf,
        "income_growth_rates": income_growth_tf,
        "rwa_intensity": rwa_intensity_tf,
        "tier1_target_ratio": tier1_tf
        if tier1_tf is not None
        else _missing_field("Tier1 Target Ratio", "Missing Tier 1 ratio"),
        "initial_capital": total_equity_tf,
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

    params = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "initial_net_income": initial_net_income,
        "income_growth_rates": income_growth_tf.value,
        "rwa_intensity": rwa_intensity_tf.value,
        "tier1_target_ratio": tier1_tf.value if tier1_tf is not None else None,
        "initial_capital": initial_capital,
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

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
        ),
    )


def _build_residual_income_params(
    ticker: str | None,
    latest: FinancialReport,
    *,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    book_value_tf = base.total_equity
    shares_tf = _resolve_shares_outstanding(
        filing_shares_tf=base.shares_outstanding,
        market_snapshot=market_snapshot,
        assumptions=assumptions,
    )
    market_shares = _market_float(market_snapshot, "shares_outstanding")
    shares_source = (
        "market_data" if market_shares is not None and market_shares > 0 else "filing"
    )

    current_book_value = _value_or_missing(book_value_tf, "current_book_value", missing)
    shares_outstanding = _value_or_missing(shares_tf, "shares_outstanding", missing)
    current_price = _market_float(market_snapshot, "current_price")

    missing.extend(["projected_residual_incomes", "required_return", "terminal_growth"])

    trace_inputs: dict[str, TraceInput] = {
        "current_book_value": book_value_tf,
        "shares_outstanding": shares_tf,
    }

    params = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "current_book_value": current_book_value,
        "projected_residual_incomes": None,
        "required_return": None,
        "terminal_growth": None,
        "terminal_residual_income": None,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
    }

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=shares_source,
        ),
    )


def _build_eva_params(
    ticker: str | None,
    latest: FinancialReport,
    *,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base

    equity_tf = base.total_equity
    debt_tf = base.total_debt
    cash_tf = base.cash_and_equivalents
    shares_tf = _resolve_shares_outstanding(
        filing_shares_tf=base.shares_outstanding,
        market_snapshot=market_snapshot,
        assumptions=assumptions,
    )
    market_shares = _market_float(market_snapshot, "shares_outstanding")
    shares_source = (
        "market_data" if market_shares is not None and market_shares > 0 else "filing"
    )
    preferred_tf = base.preferred_stock

    if equity_tf.value is None or debt_tf.value is None or cash_tf.value is None:
        invested_capital_tf = _missing_field(
            "Invested Capital", "Missing equity, debt, or cash"
        )
    else:
        invested_capital_tf = _computed_field(
            name="Invested Capital",
            value=(
                float(equity_tf.value) + float(debt_tf.value) - float(cash_tf.value)
            ),
            op_code="INVESTED_CAPITAL",
            expression="TotalEquity + TotalDebt - Cash",
            inputs={
                "Total Equity": equity_tf,
                "Total Debt": debt_tf,
                "Cash": cash_tf,
            },
        )

    current_invested_capital = _value_or_missing(
        invested_capital_tf, "current_invested_capital", missing
    )
    shares_outstanding = _value_or_missing(shares_tf, "shares_outstanding", missing)
    cash = _value_or_missing(cash_tf, "cash", missing)
    total_debt = _value_or_missing(debt_tf, "total_debt", missing)
    preferred_stock = _value_or_missing(preferred_tf, "preferred_stock", missing)
    current_price = _market_float(market_snapshot, "current_price")

    missing.extend(["projected_evas", "wacc", "terminal_growth"])

    trace_inputs: dict[str, TraceInput] = {
        "current_invested_capital": invested_capital_tf,
        "cash": cash_tf,
        "total_debt": debt_tf,
        "preferred_stock": preferred_tf,
        "shares_outstanding": shares_tf,
    }

    params = {
        "ticker": ticker or "UNKNOWN",
        "rationale": "Derived from SEC XBRL (financial reports).",
        "current_invested_capital": current_invested_capital,
        "projected_evas": None,
        "wacc": None,
        "terminal_growth": None,
        "terminal_eva": None,
        "cash": cash,
        "total_debt": total_debt,
        "preferred_stock": preferred_stock,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
    }

    return ParamBuildResult(
        params=params,
        trace_inputs=trace_inputs,
        missing=_dedupe_missing(missing),
        assumptions=assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=shares_source,
        ),
    )
