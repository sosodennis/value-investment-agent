from __future__ import annotations

from typing import Protocol, TypedDict

from src.agents.fundamental.forward_signals.interface.contracts import (
    ForwardSignalPayload,
)
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
    ) -> tuple[list[JSONObject], list[ForwardSignalPayload] | None] | None: ...


class FundamentalFinancialPayload(TypedDict):
    financial_reports: list[JSONObject]
    forward_signals: list[ForwardSignalPayload] | None
    diagnostics: JSONObject | None
    quality_gates: JSONObject | None


class IFundamentalFinancialPayloadProvider(Protocol):
    def __call__(
        self, ticker: str, *, years: int = 3
    ) -> FundamentalFinancialPayload: ...


class IMarketSnapshot(Protocol):
    def to_mapping(self) -> JSONObject: ...


class IFundamentalMarketDataService(Protocol):
    def get_market_snapshot(self, ticker_symbol: str) -> IMarketSnapshot: ...
