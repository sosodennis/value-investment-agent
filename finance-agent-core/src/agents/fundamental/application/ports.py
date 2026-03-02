from __future__ import annotations

from typing import Protocol

from src.shared.kernel.types import JSONObject


class IFundamentalReportRepo(Protocol):
    async def save_financial_reports(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_financial_reports(
        self, artifact_id: str
    ) -> list[JSONObject] | None: ...

    async def load_financial_reports_bundle(
        self, artifact_id: str
    ) -> tuple[list[JSONObject], list[JSONObject] | None] | None: ...


class IFundamentalFinancialPayloadProvider(Protocol):
    def __call__(self, ticker: str, *, years: int = 3) -> JSONObject: ...


class IMarketSnapshot(Protocol):
    def to_mapping(self) -> JSONObject: ...


class IFundamentalMarketDataService(Protocol):
    def get_market_snapshot(self, ticker_symbol: str) -> IMarketSnapshot: ...
