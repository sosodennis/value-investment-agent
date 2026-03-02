from __future__ import annotations

from src.shared.kernel.traceable import TraceableField

from .base_model_income_cashflow_component_extraction_service import (
    extract_income_cashflow_component_fields,
)
from .base_model_income_cashflow_config_service import (
    build_income_cashflow_config_bundle,
)
from .base_model_income_cashflow_contracts import (
    BuildConfigFn,
    IncomeCashflowDerivedFields,
    IncomeCashflowOps,
    ResolveConfigsFn,
)
from .base_model_income_cashflow_derived_metrics_service import (
    build_income_cashflow_derived_metrics,
)
from .extractor import SECReportExtractor


def build_income_cashflow_and_derived_fields(
    *,
    extractor: SECReportExtractor,
    resolve_configs: ResolveConfigsFn,
    build_config: BuildConfigFn,
    ops: IncomeCashflowOps,
    bs_statement_tokens: list[str],
    is_statement_tokens: list[str],
    cf_statement_tokens: list[str],
    usd_units: list[str],
    current_assets: TraceableField[float],
    current_liabilities: TraceableField[float],
    total_debt: TraceableField[float],
    total_equity: TraceableField[float],
    cash_and_equivalents: TraceableField[float],
) -> IncomeCashflowDerivedFields:
    config_bundle = build_income_cashflow_config_bundle(
        resolve_configs=resolve_configs,
        build_config=build_config,
        bs_statement_tokens=bs_statement_tokens,
        is_statement_tokens=is_statement_tokens,
        cf_statement_tokens=cf_statement_tokens,
        usd_units=usd_units,
    )

    components = extract_income_cashflow_component_fields(
        extractor=extractor,
        config_bundle=config_bundle,
        ops=ops,
    )

    derived_metrics = build_income_cashflow_derived_metrics(
        components=components,
        current_assets=current_assets,
        current_liabilities=current_liabilities,
        total_debt=total_debt,
        total_equity=total_equity,
        cash_and_equivalents=cash_and_equivalents,
        ops=ops,
    )

    return IncomeCashflowDerivedFields(
        preferred_stock=components.preferred_stock,
        total_revenue=components.total_revenue,
        operating_income=components.operating_income,
        income_before_tax=components.income_before_tax,
        interest_expense=components.interest_expense,
        depreciation_and_amortization=components.depreciation_and_amortization,
        share_based_compensation=components.share_based_compensation,
        net_income=components.net_income,
        income_tax_expense=components.income_tax_expense,
        ebitda=components.ebitda,
        operating_cash_flow=components.operating_cash_flow,
        dividends_paid=components.dividends_paid,
        working_capital=derived_metrics.working_capital,
        effective_tax_rate=derived_metrics.effective_tax_rate,
        interest_cost_rate=derived_metrics.interest_cost_rate,
        ebit_margin=derived_metrics.ebit_margin,
        net_margin=derived_metrics.net_margin,
        invested_capital=derived_metrics.invested_capital,
        nopat=derived_metrics.nopat,
        roic=derived_metrics.roic,
    )


__all__ = [
    "BuildConfigFn",
    "IncomeCashflowDerivedFields",
    "IncomeCashflowOps",
    "ResolveConfigsFn",
    "build_income_cashflow_and_derived_fields",
]
