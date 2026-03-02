from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class MarketDatum:
    value: float | None
    source: str
    as_of: str | None = None
    quality_flags: tuple[str, ...] = ()
    license_note: str | None = None

    def to_mapping(self) -> JSONObject:
        payload: JSONObject = {
            "value": self.value,
            "source": self.source,
            "as_of": self.as_of,
            "quality_flags": list(self.quality_flags),
        }
        if self.license_note is not None:
            payload["license_note"] = self.license_note
        return payload


@dataclass(frozen=True)
class ProviderFetch:
    datums: dict[str, MarketDatum]
    warnings: tuple[str, ...] = ()


class MarketDataProvider(Protocol):
    name: str
    license_note: str

    def fetch(self, ticker_symbol: str) -> ProviderFetch: ...
