from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

from src.agents.technical.domain.shared import IndicatorSnapshot


@dataclass(frozen=True)
class IndicatorEngineAvailability:
    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class IndicatorEngineResult:
    indicators: dict[str, IndicatorSnapshot]
    degraded_reasons: list[str] = field(default_factory=list)


class IIndicatorEngine(Protocol):
    def availability(self) -> IndicatorEngineAvailability: ...

    def compute_classic_indicators(
        self,
        *,
        price_series: pd.Series,
        high_series: pd.Series,
        low_series: pd.Series,
        volume_series: pd.Series,
        latest_price: float | None,
    ) -> IndicatorEngineResult: ...
