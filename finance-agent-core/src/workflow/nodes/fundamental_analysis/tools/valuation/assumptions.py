from __future__ import annotations

from datetime import datetime

from src.common.traceable import ManualProvenance, TraceableField

# Enterprise-grade policy note:
# - Do NOT silently assume values in production.
# - Defaults are allowed only for preview/prototyping and must be surfaced for review.
# - Every assumed value must be explicitly tagged with ManualProvenance.

DEFAULT_WACC = 0.10
DEFAULT_TERMINAL_GROWTH = 0.02
DEFAULT_DA_RATE = 0.04


def assume_rate(name: str, value: float, description: str) -> TraceableField[float]:
    return TraceableField(
        name=name,
        value=value,
        provenance=ManualProvenance(
            description=description,
            author="PolicyDefault",
            modified_at=str(datetime.now()),
        ),
    )


def assume_rate_series(
    name: str, value: float, count: int, description: str
) -> TraceableField[list[float]]:
    return TraceableField(
        name=name,
        value=[value] * count,
        provenance=ManualProvenance(
            description=description,
            author="PolicyDefault",
            modified_at=str(datetime.now()),
        ),
    )
