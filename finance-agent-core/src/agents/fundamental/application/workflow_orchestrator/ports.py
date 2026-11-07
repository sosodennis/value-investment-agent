from __future__ import annotations

from typing import Protocol

from src.shared.kernel.types import JSONObject


class IMarketSnapshot(Protocol):
    def to_mapping(self) -> JSONObject: ...


class IFundamentalMarketDataService(Protocol):
    def get_market_snapshot(self, ticker_symbol: str) -> IMarketSnapshot: ...

    async def get_market_snapshot_async(
        self, ticker_symbol: str
    ) -> IMarketSnapshot: ...
