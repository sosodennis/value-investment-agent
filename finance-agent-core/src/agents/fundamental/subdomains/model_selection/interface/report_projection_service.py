from __future__ import annotations

from dataclasses import dataclass

from src.agents.fundamental.subdomains.financial_statements.interface.contracts import (
    FinancialReportModel,
    RealEstateExtensionModel,
    TraceableFieldModel,
)
from src.agents.fundamental.subdomains.model_selection.domain.entities import (
    FundamentalSelectionReport,
)
from src.agents.fundamental.subdomains.model_selection.domain.financial_math_service import (
    safe_ratio,
)
from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class FundamentalPreviewMetrics:
    revenue_raw: float | None
    net_income_raw: float | None
    total_assets_raw: float | None
    roe_ratio: float | None


def _traceable_to_float(field: TraceableFieldModel | None) -> float | None:
    if field is None:
        return None
    value = field.value
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _traceable_to_int(field: TraceableFieldModel | None) -> int | None:
    if field is None:
        return None
    value = field.value
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _traceable_to_string(field: TraceableFieldModel | None) -> str | None:
    if field is None:
        return None
    value = field.value
    if value is None or isinstance(value, bool):
        return None
    return str(value)


def project_selection_reports(
    reports_raw: list[JSONObject],
) -> list[FundamentalSelectionReport]:
    validated_reports = [
        FinancialReportModel.model_validate(report_raw) for report_raw in reports_raw
    ]
    return project_selection_reports_from_models(validated_reports)


def project_selection_reports_from_models(
    reports: list[FinancialReportModel],
) -> list[FundamentalSelectionReport]:
    projections: list[FundamentalSelectionReport] = []
    for report in reports:
        base = report.base
        extension_ffo: float | None = None
        if isinstance(report.extension, RealEstateExtensionModel):
            extension_ffo = _traceable_to_float(report.extension.ffo)

        projections.append(
            FundamentalSelectionReport(
                fiscal_year=_traceable_to_string(base.fiscal_year),
                sic_code=_traceable_to_int(base.sic_code),
                total_revenue=_traceable_to_float(base.total_revenue),
                net_income=_traceable_to_float(base.net_income),
                operating_cash_flow=_traceable_to_float(base.operating_cash_flow),
                total_equity=_traceable_to_float(base.total_equity),
                total_assets=_traceable_to_float(base.total_assets),
                extension_ffo=extension_ffo,
            )
        )
    return projections


def extract_latest_preview_metrics(
    financial_reports: list[FundamentalSelectionReport],
) -> FundamentalPreviewMetrics | None:
    if not financial_reports:
        return None

    latest = financial_reports[0]
    net_income = latest.net_income
    total_equity = latest.total_equity
    return FundamentalPreviewMetrics(
        revenue_raw=latest.total_revenue,
        net_income_raw=net_income,
        total_assets_raw=latest.total_assets,
        roe_ratio=safe_ratio(net_income, total_equity),
    )
