from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class MarketDatum:
    value: float | None
    source: str
    as_of: str | None = None
    horizon: str | None = None
    update_cadence_days: int | None = None
    source_detail: str | None = None
    quality_flags: tuple[str, ...] = ()
    staleness: dict[str, str | int | bool | None] | None = None
    fallback_reason: str | None = None
    license_note: str | None = None

    def to_mapping(self) -> JSONObject:
        payload: JSONObject = {
            "value": self.value,
            "source": self.source,
            "as_of": self.as_of,
            "quality_flags": list(self.quality_flags),
        }
        if self.horizon is not None:
            payload["horizon"] = self.horizon
        if isinstance(self.update_cadence_days, int) and self.update_cadence_days > 0:
            payload["update_cadence_days"] = self.update_cadence_days
        if self.source_detail is not None:
            payload["source_detail"] = self.source_detail
        if isinstance(self.staleness, dict):
            payload["staleness"] = dict(self.staleness)
        if self.fallback_reason is not None:
            payload["fallback_reason"] = self.fallback_reason
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
