from __future__ import annotations

from typing import Protocol, TypedDict

from src.agents.fundamental.capabilities.forward_signals.public import (
    ForwardSignalPayload,
)
from src.shared.kernel.types import JSONObject


class FundamentalFinancialStatementsPayload(TypedDict):
    financial_reports: list[JSONObject]
    diagnostics: JSONObject | None
    quality_gates: JSONObject | None


class IFundamentalFinancialStatementsProvider(Protocol):
    def __call__(
        self, ticker: str, *, years: int = 3
    ) -> FundamentalFinancialStatementsPayload: ...


class IFundamentalForwardSignalsProvider(Protocol):
    def __call__(
        self, *, ticker: str, reports_raw: list[JSONObject]
    ) -> list[ForwardSignalPayload] | None: ...


class IMarketSnapshot(Protocol):
    def to_mapping(self) -> JSONObject: ...


class IFundamentalMarketDataService(Protocol):
    def get_market_snapshot(self, ticker_symbol: str) -> IMarketSnapshot: ...

    async def get_market_snapshot_async(
        self, ticker_symbol: str
    ) -> IMarketSnapshot: ...
