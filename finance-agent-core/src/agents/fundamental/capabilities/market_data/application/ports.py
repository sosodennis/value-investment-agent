from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain.market_datum import MarketDatum


@dataclass(frozen=True)
class ProviderFetch:
    datums: dict[str, MarketDatum]
    warnings: tuple[str, ...] = ()


class MarketDataProvider(Protocol):
    name: str
    license_note: str

    def fetch(self, ticker_symbol: str) -> ProviderFetch: ...
