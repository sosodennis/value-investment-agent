from __future__ import annotations

from dataclasses import dataclass, field

from .timeframe import TimeframeCode

Scalar = float | int | str | bool | None


@dataclass(frozen=True)
class PriceBar:
    timestamp: str
    price: float
    volume: float | None = None


@dataclass(frozen=True)
class PriceSeries:
    timeframe: TimeframeCode
    start: str
    end: str
    price_series: dict[str, float | None]
    volume_series: dict[str, float | None]
    open_series: dict[str, float | None] | None = None
    high_series: dict[str, float | None] | None = None
    low_series: dict[str, float | None] | None = None
    close_series: dict[str, float | None] | None = None
    timezone: str | None = None
    metadata: dict[str, Scalar] = field(default_factory=dict)
