from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FinancialHealthInsights:
    fiscal_year: str
    net_income: float | None
    total_equity: float | None
    operating_cash_flow: float | None
    roe: float | None


@dataclass(frozen=True)
class FundamentalPreviewMetrics:
    revenue_raw: float | None
    net_income_raw: float | None
    total_assets_raw: float | None
    roe_ratio: float | None


@dataclass(frozen=True)
class FundamentalSelectionReport:
    fiscal_year: str | None
    sic_code: int | None
    total_revenue: float | None
    net_income: float | None
    operating_cash_flow: float | None
    total_equity: float | None
    total_assets: float | None
    extension_ffo: float | None
