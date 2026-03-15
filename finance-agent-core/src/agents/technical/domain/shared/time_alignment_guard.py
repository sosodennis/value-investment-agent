from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .price_bar import PriceSeries
from .timeframe import TimeframeCode


@dataclass(frozen=True)
class AlignmentReport:
    schema_version: str
    anchor_timeframe: TimeframeCode
    input_timeframes: list[TimeframeCode]
    alignment_window_start: str
    alignment_window_end: str
    rows_before: int
    rows_after: int
    dropped_rows: int
    gap_count: int
    gap_samples: list[str] = field(default_factory=list)
    look_ahead_detected: bool = False
    notes: list[str] = field(default_factory=list)


class TimeAlignmentGuard(Protocol):
    def validate(
        self,
        *,
        anchor: TimeframeCode,
        frames: dict[TimeframeCode, PriceSeries],
    ) -> AlignmentReport: ...
