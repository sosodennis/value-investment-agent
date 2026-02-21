from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from math import sqrt

from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
)
from src.shared.kernel.types import JSONObject

from .assumptions import (
    DEFAULT_HIGH_GROWTH_TRIGGER,
    DEFAULT_LONG_RUN_GROWTH_TARGET,
    blend_growth_rate,
    project_growth_rate_series,
)
from .param_builders.bank import build_bank_payload
from .param_builders.context import BuilderContext
from .param_builders.eva import build_eva_payload
from .param_builders.multiples import build_ev_ebitda_payload, build_ev_revenue_payload
from .param_builders.reit import build_reit_payload
from .param_builders.residual_income import build_residual_income_payload
from .param_builders.saas import build_saas_payload
from .report_contract import (
    FinancialReport,
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


ModelParamBuilder = Callable[
    [str | None, FinancialReport, list[FinancialReport], Mapping[str, object] | None],
    ParamBuildResult,
]


PROJECTION_YEARS = 5
DEFAULT_MARKET_RISK_PREMIUM = 0.05
DEFAULT_MAINTENANCE_CAPEX_RATIO = 0.8
DEFAULT_MONTE_CARLO_ITERATIONS = 300
DEFAULT_MONTE_CARLO_SEED = 42
DEFAULT_TIME_ALIGNMENT_MAX_DAYS = 365
DEFAULT_TIME_ALIGNMENT_POLICY = "warn"


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

    model_builder = _get_model_builder(model_type)
    if model_builder is None:
        log_event(
            logger,
            event="valuation_params_build_failed",
            message="valuation parameter build failed due to unsupported model",
            fields={"model_type": model_type, "ticker": ticker},
        )
        raise ValueError(f"Unsupported model type for SEC XBRL builder: {model_type}")
    result = model_builder(
        ticker,
        latest,
        reports_sorted,
        market_snapshot=market_snapshot,
    )
    result = _apply_time_alignment_guard(
        result=result,
        latest=latest,
        market_snapshot=market_snapshot,
    )

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


def _env_text(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    return normalized if normalized else default


def _parse_iso_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        pass

    try:
        parsed_date = date.fromisoformat(text[:10])
    except ValueError:
        return None
    return datetime.combine(parsed_date, datetime.min.time(), tzinfo=UTC)


def _merge_metadata(base: JSONObject, extra: JSONObject) -> JSONObject:
    merged: JSONObject = dict(base)
    for key, value in extra.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            nested = dict(existing)
            nested.update(dict(value))
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def _apply_time_alignment_guard(
    *,
    result: ParamBuildResult,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    if market_snapshot is None:
        return result

    as_of_raw = market_snapshot.get("as_of")
    period_end_raw = latest.base.period_end_date.value
    as_of_dt = _parse_iso_datetime(as_of_raw)
    period_end_dt = _parse_iso_datetime(period_end_raw)
    if as_of_dt is None or period_end_dt is None:
        return result

    threshold_days = _env_int(
        "FUNDAMENTAL_TIME_ALIGNMENT_MAX_DAYS",
        DEFAULT_TIME_ALIGNMENT_MAX_DAYS,
        minimum=0,
    )
    policy = _env_text(
        "FUNDAMENTAL_TIME_ALIGNMENT_POLICY", DEFAULT_TIME_ALIGNMENT_POLICY
    )
    snapshot_threshold = _to_int(market_snapshot.get("time_alignment_max_days"))
    snapshot_policy = _market_text(market_snapshot, "time_alignment_policy")
    if snapshot_threshold is not None and snapshot_threshold >= 0:
        threshold_days = snapshot_threshold
    if snapshot_policy in {"warn", "reject"}:
        policy = snapshot_policy
    if policy not in {"warn", "reject"}:
        policy = DEFAULT_TIME_ALIGNMENT_POLICY

    lag_days = int((as_of_dt.date() - period_end_dt.date()).days)
    status = "aligned"
    assumptions = list(result.assumptions)
    if lag_days > threshold_days:
        status = "high_risk"
        assumptions.append(
            "high-risk: market_data_as_of exceeds filing_period_end by "
            f"{lag_days} days (threshold={threshold_days}, policy={policy})"
        )
        if policy == "reject":
            raise ValueError(
                "Time-alignment guard rejected valuation: "
                f"market_data_as_of lag={lag_days} days > threshold={threshold_days}"
            )

    time_alignment: JSONObject = {
        "status": status,
        "policy": policy,
        "lag_days": lag_days,
        "threshold_days": threshold_days,
        "market_as_of": as_of_dt.isoformat(),
        "filing_period_end": period_end_dt.date().isoformat(),
    }
    metadata = _merge_metadata(
        result.metadata,
        {"data_freshness": {"time_alignment": time_alignment}},
    )
    return ParamBuildResult(
        params=result.params,
        trace_inputs=result.trace_inputs,
        missing=result.missing,
        assumptions=assumptions,
        metadata=metadata,
    )


def _resolve_monte_carlo_controls(
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
    context = _builder_context()
    payload = build_saas_payload(
        ticker=ticker,
        latest=latest,
        reports=reports,
        market_snapshot=market_snapshot,
        deps=context.saas_deps(),
    )
    return ParamBuildResult(
        params=payload.params,
        trace_inputs=payload.trace_inputs,
        missing=_dedupe_missing(payload.missing),
        assumptions=payload.assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=payload.shares_source,
        ),
    )


def _build_ev_revenue_params(
    ticker: str | None,
    latest: FinancialReport,
    *,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    context = _builder_context()
    payload = build_ev_revenue_payload(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
        deps=context.multiples_deps(),
    )
    return ParamBuildResult(
        params=payload.params,
        trace_inputs=payload.trace_inputs,
        missing=_dedupe_missing(payload.missing),
        assumptions=payload.assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=payload.shares_source,
        ),
    )


def _build_ev_revenue_route(
    ticker: str | None,
    latest: FinancialReport,
    _reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    return _build_ev_revenue_params(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
    )


def _build_ev_ebitda_params(
    ticker: str | None,
    latest: FinancialReport,
    *,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    context = _builder_context()
    payload = build_ev_ebitda_payload(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
        deps=context.multiples_deps(),
    )
    return ParamBuildResult(
        params=payload.params,
        trace_inputs=payload.trace_inputs,
        missing=_dedupe_missing(payload.missing),
        assumptions=payload.assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=payload.shares_source,
        ),
    )


def _build_ev_ebitda_route(
    ticker: str | None,
    latest: FinancialReport,
    _reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    return _build_ev_ebitda_params(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
    )


def _build_reit_ffo_params(
    ticker: str | None,
    latest: FinancialReport,
    *,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    context = _builder_context()
    payload = build_reit_payload(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
        deps=context.reit_deps(),
    )
    return ParamBuildResult(
        params=payload.params,
        trace_inputs=payload.trace_inputs,
        missing=_dedupe_missing(payload.missing),
        assumptions=payload.assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=payload.shares_source,
        ),
    )


def _build_reit_route(
    ticker: str | None,
    latest: FinancialReport,
    _reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    return _build_reit_ffo_params(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
    )


def _build_bank_params(
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    *,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    context = _builder_context()
    payload = build_bank_payload(
        ticker=ticker,
        latest=latest,
        reports=reports,
        market_snapshot=market_snapshot,
        deps=context.bank_deps(),
    )
    return ParamBuildResult(
        params=payload.params,
        trace_inputs=payload.trace_inputs,
        missing=_dedupe_missing(payload.missing),
        assumptions=payload.assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=payload.shares_source,
        ),
    )


def _build_residual_income_params(
    ticker: str | None,
    latest: FinancialReport,
    *,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    context = _builder_context()
    payload = build_residual_income_payload(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
        deps=context.residual_income_deps(),
    )
    return ParamBuildResult(
        params=payload.params,
        trace_inputs=payload.trace_inputs,
        missing=_dedupe_missing(payload.missing),
        assumptions=payload.assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=payload.shares_source,
        ),
    )


def _build_residual_income_route(
    ticker: str | None,
    latest: FinancialReport,
    _reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    return _build_residual_income_params(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
    )


def _build_eva_params(
    ticker: str | None,
    latest: FinancialReport,
    *,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    context = _builder_context()
    payload = build_eva_payload(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
        deps=context.eva_deps(),
    )
    return ParamBuildResult(
        params=payload.params,
        trace_inputs=payload.trace_inputs,
        missing=_dedupe_missing(payload.missing),
        assumptions=payload.assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=payload.shares_source,
        ),
    )


def _build_eva_route(
    ticker: str | None,
    latest: FinancialReport,
    _reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    return _build_eva_params(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
    )


def _get_model_builder(model_type: str) -> ModelParamBuilder | None:
    return {
        "saas": _build_saas_params,
        "bank": _build_bank_params,
        "ev_revenue": _build_ev_revenue_route,
        "ev_ebitda": _build_ev_ebitda_route,
        "reit_ffo": _build_reit_route,
        "residual_income": _build_residual_income_route,
        "eva": _build_eva_route,
    }.get(model_type)


def _builder_context() -> BuilderContext:
    return BuilderContext(
        projection_years=PROJECTION_YEARS,
        default_market_risk_premium=DEFAULT_MARKET_RISK_PREMIUM,
        default_maintenance_capex_ratio=DEFAULT_MAINTENANCE_CAPEX_RATIO,
        resolve_shares_outstanding=_resolve_shares_outstanding,
        resolve_monte_carlo_controls=_resolve_monte_carlo_controls,
        market_float=_market_float,
        value_or_missing=_value_or_missing,
        ratio=_ratio,
        subtract=_subtract,
        build_saas_growth_rates=_build_saas_growth_rates,
        repeat_rate=_repeat_rate,
        missing_field=_missing_field,
        to_float=_to_float,
        computed_field=_computed_field,
        growth_rates_from_series=_growth_rates_from_series,
    )
