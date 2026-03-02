from __future__ import annotations

from src.agents.fundamental.domain.entities import FundamentalSelectionReport
from src.agents.fundamental.domain.financial_math_service import calculate_cagr
from src.shared.cross_agent.domain.market_identity import CompanyProfile

from .model_selection_contracts import SelectionField, SelectionSignals


def collect_selection_signals(
    profile: CompanyProfile,
    financial_reports: list[FundamentalSelectionReport] | None,
) -> SelectionSignals:
    sector = _normalize(profile.sector)
    industry = _normalize(profile.industry)

    reports = financial_reports or []
    latest = _latest_report(reports)
    sic = latest.sic_code if latest is not None else None
    net_income = latest.net_income if latest is not None else None
    operating_cash_flow = latest.operating_cash_flow if latest is not None else None
    total_equity = latest.total_equity if latest is not None else None

    if profile.is_profitable is not None:
        is_profitable = profile.is_profitable
    else:
        is_profitable = net_income > 0 if net_income is not None else None

    revenue_series = [r.total_revenue for r in reports if r.total_revenue is not None]
    revenue_cagr = calculate_cagr(revenue_series)

    fields_to_check: tuple[SelectionField, ...] = (
        "total_revenue",
        "net_income",
        "operating_cash_flow",
        "total_equity",
        "total_assets",
        "extension_ffo",
    )
    data_coverage: dict[SelectionField, bool] = {
        field: (latest is not None and getattr(latest, field) is not None)
        for field in fields_to_check
    }

    return SelectionSignals(
        sector=sector,
        industry=industry,
        sic=sic,
        revenue_cagr=revenue_cagr,
        is_profitable=is_profitable,
        net_income=net_income,
        operating_cash_flow=operating_cash_flow,
        total_equity=total_equity,
        data_coverage=data_coverage,
    )


def _normalize(text: str | None) -> str:
    return (text or "").strip().lower()


def _latest_report(
    financial_reports: list[FundamentalSelectionReport],
) -> FundamentalSelectionReport | None:
    if not financial_reports:
        return None
    return financial_reports[0]
