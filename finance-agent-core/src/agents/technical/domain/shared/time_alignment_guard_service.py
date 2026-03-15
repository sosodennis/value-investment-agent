from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .price_bar import PriceSeries
from .time_alignment_guard import AlignmentReport
from .timeframe import TimeframeCode


@dataclass(frozen=True)
class TimeAlignmentGuardService:
    max_gap_samples: int = 5

    def validate(
        self,
        *,
        anchor: TimeframeCode,
        frames: dict[TimeframeCode, PriceSeries],
    ) -> AlignmentReport:
        input_timeframes = list(frames.keys())
        anchor_frame = frames.get(anchor)
        if anchor_frame is None:
            return AlignmentReport(
                schema_version="1.0",
                anchor_timeframe=anchor,
                input_timeframes=input_timeframes,
                alignment_window_start="",
                alignment_window_end="",
                rows_before=0,
                rows_after=0,
                dropped_rows=0,
                gap_count=0,
                gap_samples=[],
                look_ahead_detected=True,
                notes=["ANCHOR_FRAME_MISSING"],
            )

        anchor_index = _to_index(anchor_frame)
        if anchor_index.empty:
            return AlignmentReport(
                schema_version="1.0",
                anchor_timeframe=anchor,
                input_timeframes=input_timeframes,
                alignment_window_start="",
                alignment_window_end="",
                rows_before=0,
                rows_after=0,
                dropped_rows=0,
                gap_count=0,
                gap_samples=[],
                look_ahead_detected=True,
                notes=["ANCHOR_FRAME_EMPTY"],
            )

        min_dates = []
        max_dates = []
        look_ahead_detected = False
        for timeframe, frame in frames.items():
            frame_index = _to_index(frame)
            if frame_index.empty:
                continue
            min_dates.append(frame_index.min())
            max_dates.append(frame_index.max())
            if timeframe != anchor and frame_index.max() > anchor_index.max():
                look_ahead_detected = True

        alignment_start = max(min_dates) if min_dates else anchor_index.min()
        alignment_end = min(max_dates) if max_dates else anchor_index.max()

        mask = (anchor_index >= alignment_start) & (anchor_index <= alignment_end)
        rows_before = int(len(anchor_index))
        rows_after = int(mask.sum())
        dropped_rows = max(rows_before - rows_after, 0)

        gap_count, gap_samples = _detect_gaps(
            anchor_index[mask], anchor, max_samples=self.max_gap_samples
        )

        notes: list[str] = []
        if look_ahead_detected:
            notes.append("LOOK_AHEAD_DETECTED")
        if dropped_rows:
            notes.append("ANCHOR_ROWS_DROPPED")

        return AlignmentReport(
            schema_version="1.0",
            anchor_timeframe=anchor,
            input_timeframes=input_timeframes,
            alignment_window_start=str(alignment_start),
            alignment_window_end=str(alignment_end),
            rows_before=rows_before,
            rows_after=rows_after,
            dropped_rows=dropped_rows,
            gap_count=gap_count,
            gap_samples=gap_samples,
            look_ahead_detected=look_ahead_detected,
            notes=notes,
        )


def _to_index(series: PriceSeries) -> pd.DatetimeIndex:
    if not series.price_series:
        return pd.DatetimeIndex([])
    idx = pd.to_datetime(list(series.price_series.keys()), errors="coerce")
    idx = idx[~pd.isna(idx)]
    return pd.DatetimeIndex(sorted(idx))


def _detect_gaps(
    index: pd.DatetimeIndex,
    timeframe: TimeframeCode,
    *,
    max_samples: int,
) -> tuple[int, list[str]]:
    if len(index) < 2:
        return 0, []
    expected_seconds = _expected_step_seconds(timeframe)
    if expected_seconds is None:
        return 0, []

    diffs = index.to_series().diff().dt.total_seconds().dropna()
    gap_mask = diffs > expected_seconds * 2.5
    gap_timestamps = index[1:][gap_mask]
    samples = [ts.isoformat() for ts in gap_timestamps[:max_samples]]
    return int(gap_mask.sum()), samples


def _expected_step_seconds(timeframe: TimeframeCode) -> float | None:
    if timeframe == "1h":
        return 3600.0
    if timeframe == "1d":
        return 86400.0
    if timeframe == "1wk":
        return 604800.0
    return None
