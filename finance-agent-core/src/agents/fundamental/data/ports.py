from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from src.common.contracts import ARTIFACT_KIND_FINANCIAL_REPORTS
from src.common.types import JSONObject
from src.interface.artifact_api_models import FinancialReportsArtifactData
from src.services.artifact_manager import artifact_manager
from src.shared.data.typed_artifact_port import TypedArtifactPort


@dataclass(frozen=True)
class FundamentalReportsAdapter:
    reports: list[JSONObject]

    @staticmethod
    def _traceable_value(field: object) -> object | None:
        if field is None:
            return None
        if isinstance(field, dict):
            return field.get("value")
        return field

    @staticmethod
    def _to_number(value: object) -> float | None:
        if isinstance(value, bool):
            return None
        if not isinstance(value, int | float):
            return None
        return float(value)

    @staticmethod
    def _extract_path(report: JSONObject, path: str) -> object | None:
        cur: object | None = report
        for part in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        if isinstance(cur, dict):
            return FundamentalReportsAdapter._traceable_value(cur)
        return cur

    def latest_report(self) -> JSONObject | None:
        if not self.reports:
            return None
        latest = self.reports[0]
        if not isinstance(latest, dict):
            return None
        return latest

    def latest_value(self, path: str) -> object | None:
        report = self.latest_report()
        if report is None:
            return None
        return self._extract_path(report, path)

    def latest_number(self, path: str) -> float | None:
        return self._to_number(self.latest_value(path))

    def numeric_series(self, path: str) -> list[float]:
        series: list[float] = []
        for report in self.reports:
            if not isinstance(report, dict):
                continue
            value = self._extract_path(report, path)
            num = self._to_number(value)
            if num is not None:
                series.append(num)
        return series

    def data_coverage(self, fields: set[str]) -> dict[str, bool]:
        return {field: self.latest_value(field) is not None for field in fields}


@dataclass
class FundamentalArtifactPort:
    financial_reports_port: TypedArtifactPort[FinancialReportsArtifactData]

    @dataclass(frozen=True)
    class FundamentalHealthInsights:
        fiscal_year: str
        net_income: float | None
        total_equity: float | None
        operating_cash_flow: float | None
        roe: float | None

    def extract_latest_health_insights(
        self, financial_reports: list[JSONObject]
    ) -> FundamentalHealthInsights | None:
        adapter = FundamentalReportsAdapter(financial_reports)
        latest_report = adapter.latest_report()
        if latest_report is None:
            return None
        base = latest_report.get("base")
        if not isinstance(base, dict):
            return None

        fy_raw = adapter.latest_value("base.fiscal_year")
        fiscal_year = str(fy_raw) if fy_raw is not None else "Unknown"

        net_income = adapter.latest_number("base.net_income")
        total_equity = adapter.latest_number("base.total_equity")
        operating_cash_flow = adapter.latest_number("base.operating_cash_flow")
        roe = (
            (net_income / total_equity)
            if (net_income is not None and total_equity not in (None, 0.0))
            else None
        )
        return FundamentalArtifactPort.FundamentalHealthInsights(
            fiscal_year=fiscal_year,
            net_income=net_income,
            total_equity=total_equity,
            operating_cash_flow=operating_cash_flow,
            roe=roe,
        )

    def build_latest_health_context(self, financial_reports: list[JSONObject]) -> str:
        insights = self.extract_latest_health_insights(financial_reports)
        if insights is None:
            return ""

        lines = [f"\n\nFinancial Health Insights (FY{insights.fiscal_year}):"]
        if insights.net_income is not None:
            lines.append(f"- Net Income: ${insights.net_income:,.0f}")
        if insights.total_equity is not None:
            lines.append(f"\n- Total Equity: ${insights.total_equity:,.0f}")
        if insights.roe is not None:
            lines.append(f"\n- ROE: {insights.roe:.2%}")
        if insights.operating_cash_flow is not None:
            lines.append(f"\n- OCF: ${insights.operating_cash_flow:,.0f}")
        return "".join(lines)

    async def save_financial_reports(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.financial_reports_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_financial_reports_payload(
        self, artifact_id: str
    ) -> FinancialReportsArtifactData | None:
        return await self.financial_reports_port.load(
            artifact_id,
            context=f"artifact {artifact_id} financial_reports data",
        )

    async def load_financial_reports(self, artifact_id: str) -> list[JSONObject] | None:
        payload = await self.load_financial_reports_payload(artifact_id)
        if payload is None:
            return None
        dumped = payload.model_dump(mode="json")
        reports = dumped.get("financial_reports")
        if not isinstance(reports, list):
            raise TypeError(f"artifact {artifact_id} financial_reports must be a list")
        return cast(list[JSONObject], reports)


fundamental_artifact_port = FundamentalArtifactPort(
    financial_reports_port=TypedArtifactPort(
        manager=artifact_manager,
        kind=ARTIFACT_KIND_FINANCIAL_REPORTS,
        model=FinancialReportsArtifactData,
    )
)
