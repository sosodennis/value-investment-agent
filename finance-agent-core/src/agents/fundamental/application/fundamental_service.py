from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Protocol

from src.agents.fundamental.application.dto import FundamentalAppContextDTO
from src.agents.fundamental.application.ports import IFundamentalReportRepo
from src.agents.fundamental.domain.entities import FundamentalSelectionReport
from src.agents.fundamental.domain.services import (
    build_latest_health_context,
    resolve_calculator_model_type,
)
from src.agents.fundamental.interface.mappers import (
    build_mapper_context as build_fundamental_mapper_context,
)
from src.agents.fundamental.interface.serializers import (
    ModelSelectionLike,
    serialize_model_selection_details,
)
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject


def build_mapper_context(
    intent_ctx: dict[str, object],
    resolved_ticker: str | None,
    *,
    status: str,
    model_type: str | None = None,
    valuation_summary: str | None = None,
    assumption_breakdown: JSONObject | None = None,
    data_freshness: JSONObject | None = None,
) -> FundamentalAppContextDTO:
    return build_fundamental_mapper_context(
        intent_ctx,
        resolved_ticker,
        status=status,
        model_type=model_type,
        valuation_summary=valuation_summary,
        assumption_breakdown=assumption_breakdown,
        data_freshness=data_freshness,
    )


def build_selection_details(selection: ModelSelectionLike) -> JSONObject:
    return serialize_model_selection_details(selection)


class _BuildModelSelectionReportPayloadFn(Protocol):
    def __call__(
        self,
        *,
        ticker: str,
        model_type: str,
        company_name: str,
        sector: str,
        industry: str,
        reasoning: str,
        normalized_reports: list[JSONObject],
    ) -> JSONObject: ...


class _BuildModelSelectionArtifactFn(Protocol):
    def __call__(
        self,
        *,
        ticker: str,
        report_id: str,
        preview: JSONObject,
    ) -> AgentOutputArtifactPayload: ...


class _BuildValuationArtifactFn(Protocol):
    def __call__(
        self,
        *,
        ticker: str | None,
        model_type: str,
        reports_artifact_id: str,
        preview: JSONObject,
    ) -> AgentOutputArtifactPayload: ...


def enrich_reasoning_with_health_context(
    reasoning: str,
    financial_reports: list[FundamentalSelectionReport],
) -> str:
    if not financial_reports:
        return reasoning
    return reasoning + build_latest_health_context(financial_reports)


async def build_and_store_model_selection_artifact(
    *,
    intent_ctx: dict[str, object],
    resolved_ticker: str | None,
    model_type: str,
    reasoning: str,
    financial_reports: list[JSONObject],
    port: IFundamentalReportRepo,
    summarize_preview: Callable[
        [FundamentalAppContextDTO, list[JSONObject]], JSONObject
    ],
    normalize_model_selection_reports_fn: Callable[
        [list[JSONObject]], list[JSONObject]
    ],
    build_model_selection_report_payload_fn: _BuildModelSelectionReportPayloadFn,
    build_model_selection_artifact_fn: _BuildModelSelectionArtifactFn,
) -> tuple[AgentOutputArtifactPayload | None, str | None]:
    if not resolved_ticker:
        return None, None

    mapper_ctx = build_mapper_context(
        intent_ctx,
        resolved_ticker,
        status="done",
        model_type=model_type,
        valuation_summary=reasoning,
    )
    normalized_reports = normalize_model_selection_reports_fn(financial_reports)
    preview = summarize_preview(mapper_ctx, normalized_reports)

    full_report_data = build_model_selection_report_payload_fn(
        ticker=resolved_ticker,
        model_type=model_type,
        company_name=mapper_ctx.company_name,
        sector=mapper_ctx.sector or "Unknown",
        industry=mapper_ctx.industry or "Unknown",
        reasoning=reasoning,
        normalized_reports=normalized_reports,
    )

    timestamp = int(time.time())
    report_id = await port.save_financial_reports(
        data=full_report_data,
        produced_by="fundamental_analysis.model_selection",
        key_prefix=f"fa_{resolved_ticker}_{timestamp}",
    )

    artifact = build_model_selection_artifact_fn(
        ticker=resolved_ticker,
        report_id=report_id,
        preview=preview,
    )
    return artifact, report_id


def build_valuation_missing_inputs_update(
    *,
    fundamental: dict[str, object],
    missing_inputs: list[str],
    assumptions: list[str],
) -> JSONObject:
    fa_update = fundamental.copy()
    fa_update["missing_inputs"] = missing_inputs
    if assumptions:
        fa_update["assumptions"] = assumptions
    return {
        "fundamental_analysis": fa_update,
        "current_node": "calculation",
        "internal_progress": {"calculation": "error"},
        "node_statuses": {"fundamental_analysis": "error"},
        "error_logs": [
            {
                "node": "calculation",
                "error": f"Missing SEC XBRL inputs: {', '.join(missing_inputs)}",
                "severity": "error",
            }
        ],
    }


def build_valuation_success_update(
    *,
    fundamental: dict[str, object],
    intent_ctx: dict[str, object],
    ticker: str | None,
    model_type: str,
    reports_raw: list[JSONObject],
    reports_artifact_id: str,
    params_dump: JSONObject,
    calculation_metrics: JSONObject,
    assumptions: list[str],
    summarize_preview: Callable[
        [FundamentalAppContextDTO, list[JSONObject]], JSONObject
    ],
    build_valuation_artifact_fn: _BuildValuationArtifactFn,
    build_metadata: JSONObject | None = None,
) -> JSONObject:
    fa_update = fundamental.copy()
    fa_update["extraction_output"] = {"params": params_dump}
    fa_update["calculation_output"] = {"metrics": calculation_metrics}
    if assumptions:
        fa_update["assumptions"] = assumptions

    distribution_summary = _extract_distribution_summary(calculation_metrics)
    (
        equity_value_raw,
        intrinsic_value_raw,
        upside_potential_raw,
    ) = _resolve_preview_valuation_metrics(
        calculation_metrics=calculation_metrics,
        params_dump=params_dump,
        distribution_summary=distribution_summary,
    )
    distribution_scenarios = _build_distribution_scenarios(distribution_summary)
    assumption_breakdown = _build_assumption_breakdown(
        assumptions=assumptions,
        params_dump=params_dump,
        calculation_metrics=calculation_metrics,
    )
    data_freshness = _build_data_freshness(
        reports_raw=reports_raw,
        build_metadata=build_metadata,
    )
    app_context = build_mapper_context(
        intent_ctx,
        ticker,
        status="calculated",
        model_type=model_type,
        assumption_breakdown=assumption_breakdown,
        data_freshness=data_freshness,
    )
    preview = summarize_preview(app_context, reports_raw)
    preview.update(
        {
            "model_type": model_type,
            "equity_value": equity_value_raw,
            "intrinsic_value": intrinsic_value_raw,
            "upside_potential": upside_potential_raw,
            "status": "calculated",
        }
    )
    if distribution_summary is not None:
        preview["distribution_summary"] = distribution_summary
    if distribution_scenarios is not None:
        preview["distribution_scenarios"] = distribution_scenarios
    artifact = build_valuation_artifact_fn(
        ticker=ticker,
        model_type=model_type,
        reports_artifact_id=reports_artifact_id,
        preview=preview,
    )
    fa_update["artifact"] = artifact
    return {
        "fundamental_analysis": fa_update,
        "current_node": "calculation",
        "internal_progress": {"calculation": "done"},
        "node_statuses": {"fundamental_analysis": "done"},
        "artifact": artifact,
    }


def build_valuation_error_update(error: str) -> JSONObject:
    return {
        "error_logs": [
            {
                "node": "calculation",
                "error": error,
                "severity": "error",
            }
        ],
        "internal_progress": {"calculation": "error"},
        "node_statuses": {"fundamental_analysis": "error"},
    }


def resolve_selection_model_type(selected_model_value: str) -> str:
    return resolve_calculator_model_type(selected_model_value)


def _build_assumption_breakdown(
    *,
    assumptions: list[str],
    params_dump: JSONObject,
    calculation_metrics: JSONObject,
) -> JSONObject:
    assumption_items: list[JSONObject] = []
    for statement in assumptions:
        category = "policy"
        severity = "medium"
        normalized = statement.lower()
        if "defaulted" in normalized:
            category = "default"
            severity = "high"
        elif "blended" in normalized:
            category = "blended"
            severity = "medium"

        assumption_items.append(
            {
                "statement": statement,
                "category": category,
                "severity": severity,
            }
        )

    key_parameter_fields = (
        "wacc",
        "terminal_growth",
        "risk_free_rate",
        "beta",
        "market_risk_premium",
        "maintenance_capex_ratio",
        "cost_of_equity_strategy",
    )
    key_parameters: JSONObject = {}
    for field in key_parameter_fields:
        value = params_dump.get(field)
        if isinstance(value, str | int | float | bool):
            key_parameters[field] = value

    distribution_summary = _extract_distribution_summary(calculation_metrics)
    iterations_value = params_dump.get("monte_carlo_iterations")
    seed_value = params_dump.get("monte_carlo_seed")
    monte_carlo_enabled = False
    if isinstance(iterations_value, int) and iterations_value > 0:
        monte_carlo_enabled = True
    if distribution_summary is not None:
        monte_carlo_enabled = True

    monte_carlo: JSONObject = {"enabled": monte_carlo_enabled}
    if isinstance(iterations_value, int):
        monte_carlo["iterations"] = iterations_value
    if isinstance(seed_value, int):
        monte_carlo["seed"] = seed_value
    if distribution_summary is not None:
        diagnostics = distribution_summary.get("diagnostics")
        if isinstance(diagnostics, Mapping):
            mc_diagnostic_fields = (
                "executed_iterations",
                "configured_iterations",
                "effective_window",
                "stopped_early",
                "converged",
                "sufficient_window",
            )
            for field in mc_diagnostic_fields:
                value = diagnostics.get(field)
                if isinstance(value, bool):
                    monte_carlo[field] = value
                elif isinstance(value, int):
                    monte_carlo[field] = value
                elif isinstance(value, float):
                    monte_carlo[field] = value

    return {
        "total_assumptions": len(assumption_items),
        "assumptions": assumption_items,
        "key_parameters": key_parameters,
        "monte_carlo": monte_carlo,
    }


def _build_data_freshness(
    *,
    reports_raw: list[JSONObject],
    build_metadata: JSONObject | None,
) -> JSONObject | None:
    payload: JSONObject = {}

    statement = _extract_latest_statement_freshness(reports_raw)
    if statement is not None:
        payload["financial_statement"] = statement

    metadata_freshness = None
    if isinstance(build_metadata, Mapping):
        metadata_freshness_raw = build_metadata.get("data_freshness")
        if isinstance(metadata_freshness_raw, Mapping):
            metadata_freshness = dict(metadata_freshness_raw)

    if isinstance(metadata_freshness, dict):
        market_data_raw = metadata_freshness.get("market_data")
        if isinstance(market_data_raw, Mapping):
            market_data: JSONObject = {}
            provider = market_data_raw.get("provider")
            as_of = market_data_raw.get("as_of")
            missing_fields = market_data_raw.get("missing_fields")
            if isinstance(provider, str) and provider:
                market_data["provider"] = provider
            if isinstance(as_of, str) and as_of:
                market_data["as_of"] = as_of
            if isinstance(missing_fields, list):
                normalized_missing_fields = [
                    item for item in missing_fields if isinstance(item, str) and item
                ]
                if normalized_missing_fields:
                    market_data["missing_fields"] = normalized_missing_fields
            if market_data:
                payload["market_data"] = market_data

        shares_source = metadata_freshness.get("shares_outstanding_source")
        if isinstance(shares_source, str) and shares_source:
            payload["shares_outstanding_source"] = shares_source

    if not payload:
        return None
    return payload


def _extract_latest_statement_freshness(
    reports_raw: list[JSONObject],
) -> JSONObject | None:
    latest_fiscal_year: int | None = None
    latest_period_end: str | None = None

    for report in reports_raw:
        if not isinstance(report, Mapping):
            continue
        base_raw = report.get("base")
        if not isinstance(base_raw, Mapping):
            continue

        fiscal_year_value = _extract_traceable_scalar(base_raw.get("fiscal_year"))
        period_end_value = _extract_traceable_scalar(base_raw.get("period_end_date"))

        fiscal_year = _coerce_int(fiscal_year_value)
        period_end = (
            str(period_end_value)
            if isinstance(period_end_value, str | int | float)
            else None
        )
        if fiscal_year is None and period_end is None:
            continue

        if latest_fiscal_year is None or (
            fiscal_year is not None and fiscal_year > latest_fiscal_year
        ):
            latest_fiscal_year = fiscal_year
            latest_period_end = period_end
            continue

        if (
            latest_fiscal_year is not None
            and fiscal_year == latest_fiscal_year
            and latest_period_end is None
            and period_end is not None
        ):
            latest_period_end = period_end

    if latest_fiscal_year is None and latest_period_end is None:
        return None

    output: JSONObject = {}
    if latest_fiscal_year is not None:
        output["fiscal_year"] = latest_fiscal_year
    if latest_period_end is not None:
        output["period_end_date"] = latest_period_end
    return output


def _extract_traceable_scalar(value: object) -> object | None:
    if isinstance(value, Mapping):
        return value.get("value")
    return value


def _coerce_int(value: object) -> int | None:
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


def _extract_distribution_summary(
    calculation_metrics: JSONObject,
) -> JSONObject | None:
    direct = calculation_metrics.get("distribution_summary")
    if isinstance(direct, dict):
        return direct

    details = calculation_metrics.get("details")
    if not isinstance(details, dict):
        return None
    nested = details.get("distribution_summary")
    if isinstance(nested, dict):
        return nested
    return None


def _extract_numeric_metric(
    calculation_metrics: Mapping[str, object],
    key: str,
) -> float | None:
    value = _coerce_float(calculation_metrics.get(key))
    if value is not None:
        return value

    details = calculation_metrics.get("details")
    if isinstance(details, Mapping):
        detail_value = _coerce_float(details.get(key))
        if detail_value is not None:
            return detail_value
    return None


def _build_distribution_scenarios(
    distribution_summary: JSONObject | None,
) -> JSONObject | None:
    if distribution_summary is None:
        return None
    summary = distribution_summary.get("summary")
    if not isinstance(summary, dict):
        return None

    bear = summary.get("percentile_5")
    base = summary.get("median")
    bull = summary.get("percentile_95")
    if not (
        isinstance(bear, int | float)
        and isinstance(base, int | float)
        and isinstance(bull, int | float)
    ):
        return None

    return {
        "bear": {"label": "P5 (Bear)", "price": float(bear)},
        "base": {"label": "P50 (Base)", "price": float(base)},
        "bull": {"label": "P95 (Bull)", "price": float(bull)},
    }


def _resolve_preview_valuation_metrics(
    *,
    calculation_metrics: Mapping[str, object],
    params_dump: Mapping[str, object],
    distribution_summary: Mapping[str, object] | None,
) -> tuple[float | None, float | None, float | None]:
    equity_value = _extract_numeric_metric(calculation_metrics, "equity_value")
    intrinsic_value = _extract_numeric_metric(calculation_metrics, "intrinsic_value")
    upside_potential = _extract_numeric_metric(calculation_metrics, "upside_potential")

    if intrinsic_value is None:
        intrinsic_value = _extract_numeric_metric(
            calculation_metrics, "fair_value_per_share"
        )

    shares_outstanding = _coerce_float(params_dump.get("shares_outstanding"))
    current_price = _coerce_float(params_dump.get("current_price"))

    if intrinsic_value is None and distribution_summary is not None:
        summary_raw = distribution_summary.get("summary")
        if isinstance(summary_raw, Mapping):
            intrinsic_value = _coerce_float(summary_raw.get("median"))

    if (
        intrinsic_value is None
        and equity_value is not None
        and shares_outstanding is not None
        and shares_outstanding > 0
    ):
        intrinsic_value = equity_value / shares_outstanding

    if (
        equity_value is None
        and intrinsic_value is not None
        and shares_outstanding is not None
        and shares_outstanding > 0
    ):
        equity_value = intrinsic_value * shares_outstanding

    if (
        upside_potential is None
        and intrinsic_value is not None
        and current_price is not None
        and current_price > 0
    ):
        upside_potential = (intrinsic_value - current_price) / current_price

    return equity_value, intrinsic_value, upside_potential


def _coerce_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    if isinstance(value, Mapping):
        return _coerce_float(value.get("value"))
    return None
