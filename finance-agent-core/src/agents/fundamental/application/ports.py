from __future__ import annotations

from typing import Protocol

from src.agents.fundamental.interface.contracts import FinancialReportModel
from src.common.types import JSONObject


class IFundamentalReportRepo(Protocol):
    async def save_financial_reports(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_financial_report_models(
        self, artifact_id: str
    ) -> list[FinancialReportModel] | None: ...
