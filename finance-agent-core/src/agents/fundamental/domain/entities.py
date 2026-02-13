from __future__ import annotations

from dataclasses import dataclass

from src.agents.fundamental.domain.rules import to_number, traceable_value
from src.common.types import JSONObject


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
class FundamentalReportsAdapter:
    reports: list[JSONObject]

    def latest_report(self) -> JSONObject | None:
        if not self.reports:
            return None
        latest = self.reports[0]
        if not isinstance(latest, dict):
            return None
        return latest

    def extract_path(self, report: JSONObject, path: str) -> object | None:
        cur: object | None = report
        for part in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        if isinstance(cur, dict):
            return traceable_value(cur)
        return cur

    def latest_value(self, path: str) -> object | None:
        report = self.latest_report()
        if report is None:
            return None
        return self.extract_path(report, path)

    def latest_number(self, path: str) -> float | None:
        return to_number(self.latest_value(path))

    def numeric_series(self, path: str) -> list[float]:
        series: list[float] = []
        for report in self.reports:
            if not isinstance(report, dict):
                continue
            value = self.extract_path(report, path)
            num = to_number(value)
            if num is not None:
                series.append(num)
        return series

    def data_coverage(self, fields: set[str]) -> dict[str, bool]:
        return {field: self.latest_value(field) is not None for field in fields}
